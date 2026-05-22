# Session Recap — 2026-05-22 (Dewey RAG Rebuild + Vulkan Wedge Runbook)

This recap covers a single session with five tightly linked chapters: adding clickable kiwix links, diagnosing a GPU compute deadlock, an honest account of a flash-attention misstep, rearchitecting Dewey from a model-driven tool loop to deterministic RAG, and a current-data model evaluation that produced the final model pairing. The end result is a Dewey that streams grounded answers in ~7s and gives kids a real, clickable Wikipedia link every time.

Context: this session was designated H3a (Dewey polish) in `docs/roadmap-2026-q2.md`, picking up from yesterday's model comparison and H1 completion. Related prior recaps: `docs/recaps/2026-05-20-dewey-bringup.md` and `docs/recaps/2026-05-21-q8-coder-agent-comparison.md`.

---

## Chapter 1 — Kiwix Clickable Links

### The problem

Kids asked Dewey questions and got "I read this in Wikipedia" in the response but no way to follow up themselves. Dewey would cite a source it had fetched but hand back no URL. The original kiwix-mcp scaffold returned article content with no viewer link.

### Fix part 1 — `url` field in kiwix-mcp (`20e2b52`)

A `viewerUrl()` helper was added to kiwix-mcp that builds a deterministic viewer URL from the `/content/<book>/<path>` address. `kiwix_search`, `kiwix_search_books`, and `kiwix_get_article` all gained a `url` field. The book segment in the path already carries its own date, so the link is always correct without guessing.

### Fix part 2 — internal vs public base URL (`047ac55`)

After inspecting the running pod, a critical catch: `KIWIX_BASE_URL` is the **internal cluster service DNS** (`kiwix.kiwix.svc.cluster.local`), used to fetch content without a public round-trip. Building viewer links off it produces `http://kiwix.kiwix.svc.cluster.local/viewer#...` which a browser cannot reach.

The fix was to split the two concerns: a separate `KIWIX_PUBLIC_URL` environment variable (default: `https://kiwix.lab.mtgibbs.dev`) provides the public base. `viewerUrl()` and `publicUrl()` now reduce any content reference to its `/content/` path and prepend the public base. `source_url` in article results was corrected to the public address as well.

This catch came from checking the running state — not trusting that the change was correct because the build passed.

### Fix part 3 — `[object Object]` snippets (`25fd33a`)

Search result snippets were rendering as `[object Object]`. Root cause: kiwix-serve RSS `<description>` elements parse into objects containing highlighted `<b>` terms plus a `#text` node. `String(obj)` produces the literal string `[object Object]`. An `xmlText()` helper was added to recursively extract readable text from XML-parsed nodes.

Released as kiwix-mcp **v0.1.1** → **v0.1.3**, rolled automatically by Flux image-automation. Pi-cluster kiwix manifest bumps: `8715d16` (v0.1.1), `5266251` (v0.1.2), `ff1712d` (v0.1.3).

On the Dewey pipeline side: the prompt was tightened to guarantee a "Read it yourself" footer with the exact `url` field from the kiwix result, so the link appears in every answer.

---

## Chapter 2 — The iGPU Vulkan Compute Wedge

### Symptoms

User reported Dewey was laggy then crashing on follow-up questions. The failure mode looked like an application or model issue. Diagnostic discipline: prove the server path before blaming the client.

Ruled out, with evidence:

| Hypothesis | Evidence | Verdict |
|---|---|---|
| VRAM exhausted | `rocm-smi`: 85/103 GB used, GTX negligible | Ruled out |
| LiteLLM routing fault | Direct `ollama` API call also hung | Ruled out |
| Model failed to load | Model resident in `ollama ps` output | Ruled out |
| Kernel / hardware fault | `dmesg` clean | Ruled out |
| Container-level fix | `docker restart ollama` did NOT fix it | Ruled out |

**Actual signature:** model loaded, GPU at 0% utilization while requests hung, only health pings in Ollama logs, container restart ineffective. This pattern is a **RADV/Vulkan compute queue deadlock** — the GPU has entered a state where the iGPU compute pipeline is wedged at the host level. No container-level action can clear host-level GPU state.

**Gotcha along the way:** an `rc=127` from a `curl` call inside the ollama container was briefly misread as a hang. `curl` is not in the ollama image. The `rc=127` was the container rejecting the command; the actual hang was at the inference level.

**Recovery:** reboot the Beelink (`ansible -m reboot`). Inference returned with 0.7s TTFT on the next request.

A runbook was written into `docs/beelink-ai-stack.md` (committed in `9c688d3`): fast-confirm signature (model loaded + GPU 0% + no dmesg fault + container restart ineffective = wedge), single recovery step (reboot), and the mitigations shipped in the same session.

---

## Chapter 3 — The Flash-Attention Misstep (Captured Honestly)

As a *guess* to prevent the Vulkan wedge from recurring, two changes were committed to beelink-ansible (`b825458`):

- `OLLAMA_FLASH_ATTENTION=0` — hypothesis: FA might be a contributing factor
- `OLLAMA_MAX_LOADED_MODELS=5 → 3` — reduce concurrent GPU pressure

The FA=0 change was wrong. The reboot was the real fix; FA=0 was unproven. The consequence surfaced quickly: FA=0 bloats the KV cache because flash attention is what allows Ollama to tile the KV computation efficiently. With FA disabled, `gemma3:27b` at a 32K context no longer fit in VRAM — Ollama silently placed it **100% on CPU** (VRAM utilization was 159 MB while a 25 GB model nominally "ran"). A ~42s dense answer confirmed CPU placement.

Reverted in beelink-ansible `14cf339`: `OLLAMA_FLASH_ATTENTION` removed (inherits FA=1 default), `MAX_LOADED=3` retained (reasonable concurrent-model limit). The runbook in `docs/beelink-ai-stack.md` was corrected to reflect that FA was not the cause (`a632758`).

**Lesson:** don't ship unproven preventive guesses. The diagnostic already found the root cause (host GPU state, reboot required); inventing a secondary mitigation without evidence creates new failure modes. Verify the running state before and after any config change.

---

## Chapter 4 — Dewey Rearchitected: Tool Loop → Deterministic RAG

### Why the tool loop failed

The original Dewey pipeline (from the 2026-05-20 bringup) used a model-driven tool loop: the LLM decided when to call `kiwix_search` / `kiwix_get_article`, received results, and decided when to answer. This was fragile on `qwen3.5:9b`:

- Text-format `<tool_call>` blocks (the qwen3 dual-emit quirk) required a fallback parser; without it, second tool calls were silently dropped
- The model would narrate its search process instead of giving an answer
- `/no_think` could not suppress the extended hidden reasoning path: `drop_params:true` in LiteLLM strips API-level thinking toggles, and the Ollama OpenAI endpoint does not honor `think:false` — so hybrid-thinking models leak internal monologue regardless of the flag

The entire failure class is architectural, not a tuning problem.

### The RAG rebuild

Rebuilt as **deterministic RAG**: the pipeline owns all retrieval; the model is only called for two fixed tasks.

```
User message
    │
    ▼
[LLM: keyword extraction]
    │  (small model, one call, no tools)
    ▼
kiwix_search(keywords) → top results
    │
    ▼
kiwix_get_article(best result url)
    │
    ▼
[LLM: grounded answer]
    │  (answer model, one call, article as context)
    ▼
Streamed answer + "Read it yourself: <url>"
```

No model tool calls. No loop. No tool-call parser. No thinking-mode leakage. The model cannot go off-script because it is never handed a tool.

An interim step ran RAG on `gemma3:27b` (beelink-ansible `14cf339`) and confirmed the architecture worked — but at ~42s for a dense answer, too slow for kids. The model selection chapter resolved this.

---

## Chapter 5 — Model Evaluation and Final Model Pairing

### The intervention

Rather than iterating off pre-pulled models and training-knowledge guesses, the user halted to do current-data research. The result is `docs/model-eval-2026-05.md`, which documents the full evaluation against mid-2026 HuggingFace options for the Strix Halo box.

**The hardware constraint that drives everything:** inference on the Beelink is memory-bandwidth-bound at ~215 GB/s. Tokens per second scales with *active* parameters, not total parameters. Dense models lose; high-sparsity MoE wins.

**The behavioral constraint that drives model selection:** hybrid-thinking models (those that have a thinking mode that can nominally be disabled) are disqualified. Via the Ollama + LiteLLM path, `drop_params:true` strips API-level thinking toggles and the Ollama OpenAI endpoint does not honor `think:false`. These models leak reasoning regardless. The requirement is **dedicated non-thinking `-Instruct` checkpoints** — models that were never trained with thinking tokens, not ones where thinking is switched off.

### Picks

| Role | Model | Why |
|---|---|---|
| Answer / summarizer | `Qwen3-30B-A3B-Instruct-2507` | MoE 30B/~3.3B active, dedicated non-thinking Instruct, ~62–96 tok/s, clean Ollama load, known-good on this box |
| Keyword / query-rewrite | `Qwen3-4B-Instruct-2507` | Dedicated non-thinking Instruct, trivially fast, markedly better terse instruction following than `gemma3:4b` |

The quality ceiling is `Qwen3-Next-80B-A3B-Instruct` via llama.cpp (~59 tok/s, flagship-class synthesis). The user chose the Ollama-native 30B for simplicity and always-on availability in family mode — the 80B requires llama.cpp and sole-tenancy.

Both models were pulled from HuggingFace via `ollama pull`, copied to clean tags with `ollama cp`, registered in LiteLLM via `POST /model/new`, and added to the Dewey virtual key's model allowlist.

### Streaming

The answer call was changed to a **streaming generator** with SSE passthrough to the OWUI client. The kid sees the answer begin typing at ~7s instead of waiting 42s for a spinner to resolve. Verified: 881 stream chunks, rich multi-section answer with the correct `Pastel` article link (no hallucinated URL patterns). beelink-ansible commit `6564888`.

The prompt was also tightened: the answer model is instructed to use **only the exact `url` provided** from the kiwix result. The 30B was previously guessing URL path patterns and producing broken links; this constraint kills that behavior.

---

## Key Lessons

### Diagnostic discipline: check every layer

Both the internal-vs-public URL bug and the FA/CPU-placement bug came from inspecting the *running* state — not trusting that the change was correct because the build was green or the first test passed. A cached success, a passing CI, or a model nominally "running" are not proof that the system is behaving correctly. Always verify against the actual running artifact.

### Don't ship unproven preventive guesses

The flash-attention misstep is the canonical example. The root cause was identified (host GPU state, reboot required). FA=0 was a guess layered on top of a solved problem — and it introduced a new failure mode (silent CPU placement) that was harder to notice than the original wedge. The runbook for the Vulkan wedge is: reboot. That is the complete answer.

### Deterministic RAG beats model-driven tool loops for weak or quirky local models

When the retrieval logic is in the pipeline code rather than delegated to the model, the entire failure class of "model decides not to call the tool" or "model calls the tool as plaintext" disappears. For a kids' study assistant where correctness and reliability matter more than model autonomy, this is the right architecture. Reserve model-driven tool loops for surfaces (like the ops pipeline) where the model has proven agentic capability.

### Pick models from current data, not training knowledge

The model-evaluation step — halting to research mid-2026 HuggingFace options — produced a materially better outcome than iterating on the pre-pulled model set. The 30B Qwen3 Instruct is a measurable quality jump over `gemma3:27b` while being faster and not leaking reasoning. Training-knowledge model recommendations go stale quickly; for production choices, current data is worth the research cost.

### Prefer dedicated non-thinking `-Instruct` checkpoints on this stack

The Ollama + LiteLLM path cannot reliably suppress thinking. `drop_params:true` strips the API-level thinking toggle; the Ollama OpenAI endpoint does not honor `think:false`. Any model that was trained with thinking tokens will leak them. This constraint is permanent for this stack and should be treated as a hard requirement in all future model selections for Dewey.

---

## Commits

### pi-cluster repo

| Hash | Date | Subject |
|---|---|---|
| `8715d16` | 2026-05-22 | chore: update kiwix-mcp to ghcr.io/mtgibbs/kiwix-mcp:0.1.1 |
| `5266251` | 2026-05-22 | chore: update kiwix-mcp to ghcr.io/mtgibbs/kiwix-mcp:0.1.2 |
| `9c688d3` | 2026-05-21 | docs(beelink): runbook for the iGPU Vulkan compute wedge |
| `ff1712d` | 2026-05-22 | chore: update kiwix-mcp to ghcr.io/mtgibbs/kiwix-mcp:0.1.3 |
| `a632758` | 2026-05-22 | docs(beelink): correct runbook — FA=0 reverted (breaks GPU placement) |
| `3f203b6` | 2026-05-22 | docs: model evaluation for Dewey RAG (2026-05) |
| `f93c0d2` | 2026-05-22 | docs(beelink): Dewey rearchitected to RAG + streaming on Qwen3 Instruct |

### kiwix-mcp repo

| Hash | Subject |
|---|---|
| `20e2b52` | feat: return a clickable viewer url on search + article results |
| `047ac55` | fix: build user-facing links from a PUBLIC base, not the fetch host |
| `25fd33a` | fix: flatten XML-parsed search snippets (no more "[object Object]") |

### beelink-ansible repo (local-only)

| Hash | Subject |
|---|---|
| `84e5f37` | feat(dewey): always give kids a clickable kiwix link |
| `b825458` | fix(beelink): mitigate Vulkan wedge + harden Dewey tool loop |
| `14cf339` | feat(dewey): deterministic RAG on gemma3-27b; revert FA=0 |
| `6564888` | feat(dewey): stream answers; switch to Qwen3 Instruct models |

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| kiwix-mcp | v0.1.3 | `url` field in all results; public base URL; no `[object Object]` snippets |
| Dewey architecture | Deterministic RAG | Pipeline retrieves; model summarizes; no tool-call loop |
| Answer model | `Qwen3-30B-A3B-Instruct-2507` | Non-thinking Instruct; ~62–96 tok/s; 100% VRAM |
| Keyword model | `Qwen3-4B-Instruct-2507` | Non-thinking Instruct; trivially fast |
| Streaming | SSE generator | ~7s TTFT; 881 chunks verified |
| Clickable links | "Read it yourself" footer in every answer | Exact `url` from kiwix result; no guessed patterns |
| Vulkan wedge runbook | Written in `docs/beelink-ai-stack.md` | Recovery: reboot Beelink |
| `OLLAMA_FLASH_ATTENTION` | Reverted to default (on) | FA=0 was wrong; was causing silent CPU placement |
| `OLLAMA_MAX_LOADED_MODELS` | `3` | Reduced from 5; kept after FA revert |
| Model evaluation | `docs/model-eval-2026-05.md` | Current-data research; permanent reference for future model selections |

---

## Related Documentation

- `docs/model-eval-2026-05.md` — full current-data model evaluation with rankings, hardware framing, and rationale
- `docs/beelink-ai-stack.md` — Vulkan wedge runbook + corrected FA note
- `docs/recaps/2026-05-20-dewey-bringup.md` — original Dewey architecture (tool loop era)
- `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` — the model benchmarking and `OLLAMA_CONTEXT_LENGTH` fix that set the stage for this session

---

## What Remains

- [ ] Verify `Qwen3-Next-80B-A3B-Instruct` via llama.cpp-vulkan as a quality ceiling option for Dewey (the `aimode work` pattern from the ops pipeline applies)
- [ ] Pre-warm Dewey's `Qwen3-30B-A3B-Instruct-2507` in the Ansible post-deploy play (currently the first request takes the model-load hit)
- [ ] CARL's inference endpoint is still the in-cluster `ollama` namespace — evaluate migrating to the Beelink LiteLLM gateway so all inference goes through one authenticated layer
- [ ] Beelink iGPU GPU-utilization metric in Grafana — the Vulkan wedge is detectable (GPU at 0% under load) but only if the metric is being scraped; close the visibility gap
- [ ] Authelia SSO for Dewey (H2, deferred)
