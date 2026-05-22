# scripts/

Local-stack helper scripts. General-purpose (usable across projects) but documented
and bootstrapped from this repo since they depend on the home lab stack.

## `oc` — opencode launcher

Wraps `opencode` so the LiteLLM/qwen key is fetched from 1Password at startup (one
biometric prompt) and handed to opencode's process env only — never exported to your
shell or written to disk. Same pattern as the MCP auth wrappers.

**Bootstrap onto any machine:**

```bash
cp scripts/oc ~/.local/bin/oc && chmod +x ~/.local/bin/oc   # ~/.local/bin must be on PATH
```

**Use:**

```bash
oc                 # interactive TUI (qwen3-coder via ai.lab)
oc run "do thing"  # headless one-shot
```

**Other machines / other key:** override the vault reference —

```bash
OC_KEY_REF="op://work-vault/opencode/key" oc
```

Requires: `op` (1Password CLI, signed in or desktop-integration enabled), `opencode`,
and a project `opencode.json` whose provider reads `{env:OPENCODE_QWEN_KEY}`.
