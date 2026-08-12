#!/usr/bin/env python3
"""
model-watch — monthly local-model candidate digest

This script sweeps the HuggingFace API for recently-trending text-generation models,
computes the intake gates from real API metadata, assigns each candidate a bucket,
and pushes a digest to ntfy with LLM summary.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import ssl
import re
from datetime import datetime, timedelta, timezone

# Constants
HF_API_BASE = "https://huggingface.co/api"
HF_RAW_BASE = "https://huggingface.co"
NTFY_TOPIC = "model-watch"
LITELLM_URL = "https://ai.lab.mtgibbs.dev/v1"
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def fetch_with_retry(url, retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT):
    """Fetch URL with retry logic."""
    for attempt in range(retries):
        try:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            response = urllib.request.urlopen(req, timeout=timeout, context=context)
            return json.loads(response.read())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise e

def get_trending_models(window_days=45, min_likes=40):
    """Get trending models from HuggingFace API."""
    # Get models sorted by trending score with filter for text generation
    url = f"{HF_API_BASE}/models?sort=trendingScore&direction=-1&limit=60&filter=text-generation&full=true"
    
    try:
        data = fetch_with_retry(url)
        if not isinstance(data, list):
            return []
            
        # Filter by likes and date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=window_days)
        
        filtered_models = []
        for model in data:
            try:
                created_at = datetime.fromisoformat(model.get('createdAt', '').replace('Z', '+00:00'))
                if created_at < cutoff_date:
                    continue
                    
                likes = model.get('likes', 0)
                if likes < min_likes:
                    continue
                    
                filtered_models.append({
                    'id': model.get('id'),
                    'likes': likes,
                    'created': model.get('createdAt'),
                    'tags': model.get('tags', [])
                })
            except Exception:
                # Skip bad entries
                continue
                
        return filtered_models
    except Exception as e:
        print(f"Error fetching trending models: {e}", file=sys.stderr)
        return []

def is_derivative_model(tags):
    """Check if model is a derivative (quantized, finetune, merge, adapter)."""
    for tag in tags:
        if tag.startswith('base_model:'):
            return True
    return False

def get_model_details(model_id):
    """Get detailed information about a specific model."""
    url = f"{HF_API_BASE}/models/{model_id}"
    
    try:
        data = fetch_with_retry(url)
        
        # Extract key information from the response
        safetensors_total = data.get('safetensors', {}).get('total')
        config = data.get('config', {})
        card_data = data.get('cardData', {})
        license = card_data.get('license', '')
        license_name = card_data.get('license_name', '')
        
        # Get architecture info
        architectures = config.get('architectures', [])
        model_type = config.get('model_type', '')
        
        # Check for MoE parameters
        moe_config_keys = ['num_experts', 'num_local_experts', 'n_routed_experts', 'moe_num_experts',
                          'num_experts_per_tok', 'n_activated_experts', 'moe_topk']
        num_experts = None
        active_experts = None
        
        for key in moe_config_keys:
            if key in config:
                if 'expert' in key:
                    num_experts = config[key]
                elif 'active' in key or 'topk' in key:
                    active_experts = config[key]
        
        # Get license info
        if license == 'other':
            actual_license = license_name.lower() if license_name else 'unknown'
        else:
            actual_license = license.lower()
            
        return {
            'params': safetensors_total,
            'architectures': architectures,
            'model_type': model_type,
            'moe': num_experts is not None,
            'num_experts': num_experts,
            'active_experts': active_experts,
            'license': actual_license,
            'tags': data.get('tags', [])
        }
    except Exception as e:
        print(f"Error fetching model details for {model_id}: {e}", file=sys.stderr)
        return None

def calculate_q4_size(params):
    """Calculate Q4 size estimate."""
    if params is None:
        return None
    # Q4 weights ≈ params * 0.60 bytes
    q4_bytes = params * 0.60
    return q4_bytes / (1024**3)  # Convert to GB

def check_intake_gates(model_details, vram_budget_gb=96):
    """Check if model passes intake gates."""
    params = model_details.get('params')
    license = model_details.get('license', '')
    moe = model_details.get('moe', False)
    num_experts = model_details.get('num_experts')
    active_experts = model_details.get('active_experts')
    
    # License check - only allow permissive licenses
    permissive_licenses = ['apache-2.0', 'mit', 'bsd-3-clause', 'bsd-2-clause', 
                          'mpl-2.0', 'lgpl-3.0', 'agpl-3.0', 'isc', 'unlicense']
    
    # Check if license is permissive or unknown (will be classified as watch)
    if license not in permissive_licenses and license != '':
        return False, 'non-permissive license'
    
    # If no params, skip
    if params is None:
        return False, 'no parameter count'
        
    # Calculate Q4 size
    q4_gb = calculate_q4_size(params)
    
    # Check if model fits in VRAM budget (75% of available for weights)
    available_weight_vram = vram_budget_gb * 0.75
    
    if q4_gb is not None and q4_gb > available_weight_vram:
        return False, f'{q4_gb:.1f}GB exceeds {available_weight_vram:.1f}GB budget'
        
    # MoE check - for now, we'll treat MoE models as potential candidates
    # but with a warning if they're too large
    
    return True, 'passes all gates'

def classify_model(model_data, model_details):
    """Classify a model based on its details."""
    # Check if it's derivative
    if is_derivative_model(model_data.get('tags', [])):
        # For finetunes with same org, keep them; for different orgs, drop them
        model_org = model_data['id'].split('/')[0]
        base_model_tag = None
        
        for tag in model_data.get('tags', []):
            if tag.startswith('base_model:'):
                tag_parts = tag.split(':', 2)
                if len(tag_parts) >= 3:
                    base_model_tag = tag_parts[2]  # Get the base-id part
                break
                
        # If it's a finetune of a different org, skip it
        if base_model_tag and '/' in base_model_tag:
            base_org = base_model_tag.split('/')[0]
            if model_org != base_org:
                return 'skip', 'derivative repack'
    
    # Get details for intake gates
    passes_gates, reason = check_intake_gates(model_details)
    
    if not passes_gates:
        return 'skip', reason
    
    # Check if it's too large or has issues
    params = model_details.get('params')
    q4_gb = calculate_q4_size(params)
    
    if q4_gb is None:
        return 'consider', 'no size estimate'
        
    # Check if it's a good fit for our hardware (smaller than 20% of VRAM budget)
    if q4_gb < 19.2:  # 20% of 96GB
        return 'test', f'Q4 size {q4_gb:.1f}GB fits well'
    elif q4_gb < 38.4:  # 40% of 96GB
        return 'consider', f'Q4 size {q4_gb:.1f}GB is reasonable but larger than recommended'
    else:
        return 'watch', f'Q4 size {q4_gb:.1f}GB is over budget'

def get_model_reason(model_data, model_details, bucket):
    """Get a reason string for the classification."""
    params = model_details.get('params')
    license = model_details.get('license', '')
    moe = model_details.get('moe', False)
    num_experts = model_details.get('num_experts')
    active_experts = model_details.get('active_experts')
    
    if bucket == 'skip':
        return 'filtered out'
    elif bucket == 'test':
        q4_gb = calculate_q4_size(params)
        if moe and num_experts and active_experts:
            return f'MoE {params/10**9:.1f}B, {active_experts}/{num_experts} experts active, ~{q4_gb:.1f} GB at Q4'
        elif moe:
            return f'MoE {params/10**9:.1f}B with unknown expert count, ~{q4_gb:.1f} GB at Q4'
        else:
            return f'{params/10**9:.1f}B parameter model, ~{q4_gb:.1f} GB at Q4'
    elif bucket == 'consider':
        q4_gb = calculate_q4_size(params)
        if moe and num_experts and active_experts:
            return f'MoE {params/10**9:.1f}B, {active_experts}/{num_experts} experts active, ~{q4_gb:.1f} GB at Q4'
        else:
            return f'{params/10**9:.1f}B parameter model, ~{q4_gb:.1f} GB at Q4'
    elif bucket == 'watch':
        q4_gb = calculate_q4_size(params)
        return f'{params/10**9:.1f}B is over the 96 GB budget'
    
    return 'unknown'

def get_model_card_text(model_id):
    """Get model card text from HuggingFace."""
    url = f"{HF_RAW_BASE}/{model_id}/raw/main/README.md"
    
    try:
        data = fetch_with_retry(url)
        return data
    except Exception as e:
        # If we can't get the README, that's OK
        return None

def call_llm_summary(model_list):
    """Call LiteLLM to generate summary for the classified models."""
    if not model_list:
        return ""
    
    try:
        # Build the prompt with all classified models
        prompt = "Please provide a concise summary of these models. Focus on their key features and relevance for local inference.\n\n"
        
        for model in model_list:
            prompt += f"- {model['id']}: {model['reason']}\n"
        
        prompt += "\nSummarize in 1-2 sentences, highlighting which ones are most promising for local inference on hardware similar to Ryzen AI Max+ 395 with 128GB RAM and ~96GB usable VRAM."
        
        # Create request payload
        payload = {
            "model": "qwen3-30b-instruct",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that summarizes AI models for local inference. Keep responses concise and technical."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 200
        }
        
        # Set up request with headers
        req = urllib.request.Request(LITELLM_URL + "/chat/completions")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {os.environ.get('LITELLM_API_KEY', 'fake-key')}")
        
        # Send request
        response = urllib.request.urlopen(req, 
                                        data=json.dumps(payload).encode('utf-8'),
                                        timeout=REQUEST_TIMEOUT)
        
        result = json.loads(response.read())
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Error calling LLM: {e}", file=sys.stderr)
        return None

def push_ntfy_digest(summary, model_list):
    """Push digest to ntfy with fallback."""
    if not summary or not model_list:
        return False
        
    try:
        # Build the message
        title = "Model Watch Digest"
        
        # Create the body of the message
        body = f"Summary:\n{summary}\n\nModels:\n"
        for model in model_list:
            body += f"- [{model['bucket']}] {model['id']} - {model['reason']}\n"
            
        # Prepare ntfy request
        ntfy_url = f"http://ntfy.ntfy.svc.cluster.local/{NTFY_TOPIC}"
        
        req = urllib.request.Request(ntfy_url)
        req.add_header("Title", title)
        req.add_header("Content-Type", "text/plain")
        req.add_header("Authorization", f"Basic {os.environ.get('NTFY_PASSWORD', 'fake-password')}")
        req.data = body.encode('utf-8')
        
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        return response.getcode() == 200
        
    except Exception as e:
        print(f"Error pushing to ntfy: {e}", file=sys.stderr)
        return False

def main():
    # Read environment variables
    dry_run = os.environ.get('DRY_RUN', '0') == '1'
    window_days = int(os.environ.get('WINDOW_DAYS', 45))
    min_likes = int(os.environ.get('MIN_LIKES', 40))
    vram_budget_gb = float(os.environ.get('VRAM_BUDGET_GB', 96))
    
    if dry_run:
        # DRY_RUN mode - only print classifications without calling LLM or ntfy
        print(f"[{get_current_timestamp()}] DRY_RUN: Collecting models...")
        
        # Get trending models
        models = get_trending_models(window_days, min_likes)
        classified_models = []
        
        for model in models:
            details = get_model_details(model['id'])
            if not details:
                continue
                
            bucket, reason = classify_model(model, details)
            if bucket != 'skip':
                model_info = {
                    'id': model['id'],
                    'bucket': bucket,
                    'reason': reason
                }
                classified_models.append(model_info)
                
        # Print DRY_RUN output as required by spec
        for model in classified_models:
            print(f"[{model['bucket']}] {model['id']} - {model['reason']}")
            
        return 0
    
    else:
        # Normal mode - collect models, get LLM summary, and push to ntfy
        print(f"[{get_current_timestamp()}] Collecting models...")
        
        # Get trending models
        models = get_trending_models(window_days, min_likes)
        classified_models = []
        
        for model in models:
            details = get_model_details(model['id'])
            if not details:
                continue
                
            bucket, reason = classify_model(model, details)
            if bucket != 'skip':
                model_info = {
                    'id': model['id'],
                    'bucket': bucket,
                    'reason': reason
                }
                classified_models.append(model_info)
                
        # Get LLM summary
        print(f"[{get_current_timestamp()}] Generating LLM summary...")
        summary = call_llm_summary(classified_models)
        
        # If LLM call failed, still push a fallback digest
        if not summary:
            print(f"[{get_current_timestamp()}] LLM call failed, using fallback digest...")
            
            # Build fallback summary from the classified models directly
            summary = "No LLM summary available. Here are the candidates:"
            for model in classified_models:
                summary += f"\n- {model['id']}: {model['reason']}"
        
        # Push to ntfy
        print(f"[{get_current_timestamp()}] Pushing digest to ntfy...")
        success = push_ntfy_digest(summary, classified_models)
        
        if success:
            print(f"[{get_current_timestamp()}] Digest pushed successfully")
        else:
            print(f"[{get_current_timestamp()}] Failed to push digest to ntfy", file=sys.stderr)
            
        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())