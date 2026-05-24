# scripts/

Local-stack helper scripts. General-purpose (usable across projects) but documented
and bootstrapped from this repo since they depend on the home lab stack.

## Local-creds model (why no biometric per run)

The laptop↔Beelink-qwen link is a **device-to-tool** connection on a trusted machine — it
doesn't act on behalf of the cluster, it just *uses the model like a tool that belongs to the
box*. So its working creds live **locally** (no Touch-ID-per-use lockout), while the
**canonical copies stay in 1Password** for easy re-bootstrap. Crown-jewel / cluster-acting
creds stay behind the biometric, untouched. Two channels:

- **`oc run` → qwen** (HTTPS/LiteLLM): the key is cached in the **macOS Keychain** (service
  `opencode-qwen`); `oc` reads Keychain-first, 1Password as fallback. Re-seed with:
  `security add-generic-password -U -s opencode-qwen -a oc -T /usr/bin/security -w "$(op read 'op://pi-cluster/opencode-coder/password')"`
- **`ssh beelink-ai`** (host access): a private key on disk at `~/.ssh/beelink-ai` (0600),
  with `~/.ssh/config` set to `IdentityAgent none` for that host so it bypasses the 1Password
  SSH agent. Canonical copy: 1Password item `beelink-ai SSH`. Re-extract with:
  `op read 'op://pi-cluster/beelink-ai SSH/private key?ssh-format=openssh' > ~/.ssh/beelink-ai && chmod 600 ~/.ssh/beelink-ai`

## `oc` — opencode launcher

Wraps `opencode` so the LiteLLM/qwen key is loaded into opencode's process env only — never
exported to your shell. Reads the key from the Keychain (no biometric) and falls back to
1Password. Adds a watchdog timeout to `oc run`.

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
