#!/usr/bin/env python3
"""Run the read-only diagnostic exam against a local model through Goose.

Safety model: the model only ever sees READ_ONLY_TOOLS (Goose `available_tools`
allowlist) and no `developer` extension, so it has no shell. Anything not listed
here is withheld by default — a new MCP tool stays invisible until classified.
After each run the transcript is audited: any call outside the allowlist fails
the whole exam loudly.

Usage:
  python3 run.py OUT_DIR [--only id1,id2] [--model hot-coder]

Needs `goose` on PATH and the homelab MCP key (MCP_HOMELAB_API_KEY, else Goose's
homelab extension config, else `op` — never written into the repo), and GOOSE_DISABLE_KEYRING=1 if the
provider key lives in ~/.config/goose/secrets.yaml.
"""
import argparse, json, os, pathlib, subprocess, sys, time

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
SKILL = REPO / ".claude/skills/cluster-diagnostics/SKILL.md"
MCP_URL = "https://mcp.lab.mtgibbs.dev/mcp"
KEY_REF = "op://pi-cluster/mcp-homelab/api-key"

READ_ONLY_TOOLS = [
    "get_cluster_health", "get_dns_status", "test_dns_query", "diagnose_dns",
    "get_pihole_whitelist", "get_pihole_queries", "get_flux_status",
    "get_certificate_status", "get_secrets_status", "get_backup_status",
    "get_cronjob_details", "get_job_logs", "get_ingress_status",
    "get_tailscale_status", "get_media_status", "get_node_networking",
    "get_iptables_rules", "get_conntrack_entries", "curl_ingress",
    "test_pod_connectivity", "get_pod_logs", "get_pvcs", "describe_resource",
    "get_subtitle_status", "get_subtitle_history", "get_sonarr_queue",
    "get_sonarr_history", "get_radarr_queue", "get_radarr_history",
    "get_sabnzbd_queue", "get_sabnzbd_history", "get_quality_profile",
    "get_mealie_status", "search_mealie_recipes", "get_mealie_recipe",
]

INSTRUCTIONS = """You are a read-only diagnostician for a Raspberry Pi 5 K3s homelab cluster.
You reach the cluster ONLY through the `homelab` tools. You cannot change anything:
if a fix is needed, say what should be done and by whom — never claim you did it.
Base every claim on a tool result from this session. If a tool errors or returns
something unusable, say so plainly instead of guessing. Be concise.

The team's diagnostic playbook follows — trust it over your priors.

"""


def build_recipe(key: str, model: str) -> dict:
    return {
        "version": "1.0.0",
        "title": "homelab read-only diagnostic exam",
        "description": "One diagnostic question, read-only homelab tools",
        "instructions": INSTRUCTIONS + SKILL.read_text(),
        "prompt": "{{ question }}",
        "parameters": [{
            "key": "question", "input_type": "string",
            "requirement": "required", "description": "The exam question",
        }],
        "extensions": [{
            "type": "streamable_http", "name": "homelab", "uri": MCP_URL,
            "headers": {"X-API-Key": key}, "timeout": 300,
            "available_tools": READ_ONLY_TOOLS,
        }],
        "settings": {"goose_provider": "openai", "goose_model": model},
    }


def tool_calls(events):
    """Pull (tool_name, args) out of Goose stream-json events, schema-tolerant."""
    calls = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") in ("toolRequest", "tool_request"):
                tc = o.get("toolCall") or o.get("tool_call") or {}
                v = tc.get("value", tc)
                name = v.get("name") or ""
                calls.append((name.split("__")[-1], v.get("arguments")))
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for e in events:
        walk(e)
    return calls


def mcp_key() -> str:
    """Env var, else Goose's own homelab extension config, else 1Password.

    `op` needs an interactive biometric unlock, so a backgrounded run times out
    on it — the Goose config (already on this machine) is the non-interactive path.
    """
    if os.environ.get("MCP_HOMELAB_API_KEY"):
        return os.environ["MCP_HOMELAB_API_KEY"]
    cfg = pathlib.Path.home() / ".config/goose/config.yaml"
    if cfg.exists():
        ext = (yaml.safe_load(cfg.read_text()).get("extensions") or {}).get("homelab") or {}
        if (ext.get("headers") or {}).get("X-API-Key"):
            return ext["headers"]["X-API-Key"]
    return subprocess.run(["op", "read", KEY_REF], check=True,
                          capture_output=True, text=True).stdout.strip()


def answer_text(events):
    """Concatenate streamed assistant text chunks; a tool call starts a new block."""
    parts = []
    for e in events:
        m = e.get("message") or {}
        if m.get("role") != "assistant":
            continue
        for c in m.get("content", []):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") in ("toolRequest", "tool_request"):
                parts.append("\n\n")
    return "".join(parts).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--only")
    ap.add_argument("--model", default="hot-coder")
    ap.add_argument("--max-turns", default="20")
    a = ap.parse_args()

    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    qs = yaml.safe_load((HERE / "questions.yaml").read_text())["questions"]
    if a.only:
        keep = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in keep]

    key = mcp_key()
    recipe = out / ".recipe.yaml"  # holds the key: stays in the scratch out_dir
    recipe.write_text(yaml.safe_dump(build_recipe(key, a.model), sort_keys=False))
    os.chmod(recipe, 0o600)

    allowed, summary, violations = set(READ_ONLY_TOOLS), [], []
    try:
        for q in qs:
            t0 = time.time()
            p = subprocess.run(
                ["goose", "run", "--no-session", "--recipe", str(recipe),
                 "--params", f"question={q['prompt']}",
                 "--output-format", "stream-json", "--max-turns", a.max_turns],
                capture_output=True, text=True, timeout=900)
            secs = round(time.time() - t0, 1)
            (out / f"{q['id']}.jsonl").write_text(p.stdout)
            (out / f"{q['id']}.stderr").write_text(p.stderr)
            events = []
            for line in p.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            (out / f"{q['id']}.answer.md").write_text(answer_text(events))
            calls = tool_calls(events)
            bad = [c[0] for c in calls if c[0] not in allowed]
            violations += [(q["id"], b) for b in bad]
            summary.append({"id": q["id"], "rc": p.returncode, "secs": secs,
                            "tools": [c[0] for c in calls], "outside_allowlist": bad})
            print(f"{q['id']:<24} rc={p.returncode} {secs:>6}s tools={[c[0] for c in calls]}",
                  flush=True)
    finally:
        recipe.unlink(missing_ok=True)

    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    if violations:
        print(f"ALLOWLIST VIOLATION: {violations}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
