---
description: Test DNS resolution through Pi-hole and Unbound
allowed-tools: Bash(dig:*), Bash(nslookup:*), Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
argument-hint: [domain]
---

# DNS Resolution Test

Test DNS resolution through the Pi-hole + Unbound stack.

## Configuration
- Pi-hole IP: 192.168.1.55
- DNS Flow: Client → Pi-hole (53) → Unbound (5335) → Root servers
- Wildcard: *.lab.mtgibbs.dev → 192.168.1.55

## Tests to Run

Domain to test: $ARGUMENTS (default: google.com)

1. **Pi-hole resolution** (external domain):
   ```bash
   dig @192.168.1.55 <domain> +short
   ```

2. **Wildcard DNS** (internal):
   ```bash
   dig @192.168.1.55 test.lab.mtgibbs.dev +short
   ```

3. **Unbound direct** (if accessible):
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl run -it --rm dns-test --image=busybox --restart=Never -- nslookup google.com unbound.pihole.svc.cluster.local
   ```

## Expected Results

- External domains: Should return IP addresses
- *.lab.mtgibbs.dev: Should return 192.168.1.55
- Unbound direct: Should resolve via recursive lookup

## Output

Report:
- Resolution status for each test
- Response times
- Any failures or timeouts
