# Spacelift free tier — does it buy the lab anything?

**Date read:** 2026-11-18 (live reads of spacelift.io/pricing and docs.spacelift.io; no account created, nothing installed).
**Verdict:** **Skip.** Revisit only if UniFi comes under OpenTofu *and* the free tier ever gains private workers.

## TL;DR

1. **The free tier can't reach the lab.** Private worker pools are "only available on the Business plan and above" (docs: worker-pools). Business has no public price. Everything that matters here — UniFi (192.168.1.1), Beelink (192.168.1.70), the K3s API — is LAN-only, so a SaaS public runner can't touch it.
2. **The free tier has no policies and no drift detection.** Policies: "only available to paid Spacelift accounts" (docs: policy). Drift detection: Business+ and "only works on private workers". Those were the two features most likely to add something over the existing drift gate and review-hub.
3. **What's left on free overlaps with what's already here.** You get PR plans and a manual confirm click, which GitHub Actions + a PR already give you. The free plan's worker count, concurrency and run limits aren't published at all: the pricing page lists **no** workers for Free, and Starter ($399/mo, annual) is the first tier that lists "2 public workers".
4. **Security cost for no gain.** Using it means a GitHub App with checks/PR/webhook write on your repos, plus provider creds (Cloudflare token, GitHub token) stored in a SaaS control plane. That's the standing third-party credential the lab's rules are built to avoid.

## What the free tier actually is (2026-11-18)

| Item | Free | Source |
|---|---|---|
| Users | 2 | pricing |
| API keys | 1 | pricing |
| Public workers / concurrency / run minutes | **Not stated.** Free lists no workers; Starter lists "2 public workers" | pricing |
| Private (self-hosted) workers | **No.** Business+ | docs/concepts/worker-pools |
| Stack limit | Not stated | pricing, docs/product/billing |
| OPA policies (plan/approval/push/trigger/login) | **No.** "only available to paid Spacelift accounts" | docs/concepts/policy |
| Drift detection | **No.** Business+, private workers only | docs/concepts/stack/drift-detection |
| Manual confirm before apply | Yes, apparently: autodeploy off → run waits `Unconfirmed` (no plan gate stated; inferred) | docs/concepts/run/tracked |
| State hosting | Spacelift-managed S3 state (30-day noncurrent versions), or bring your own backend; exportable via `tofu state pull` | docs/vendors/terraform/state-management |
| Audit trail | Enterprise only | pricing |
| Tools | OpenTofu (first-class), Terraform, Terragrunt, Pulumi, CloudFormation, Ansible, Kubernetes (kubectl). The pricing page doesn't break "IaC support" down by tier | docs/vendors/* |
| Next tier | Starter, "Starting at $399 / mo", annual. Business/Enterprise: quote only | pricing |

Gaps worth noting: Spacelift doesn't publish free-plan run or worker limits, and the worker-pools doc gates "this feature" (whether that means public pools too is ambiguous). MQTT worker transport sunsets 2027-03-30 (switch to HTTP poll by 2027-01-01). That's only relevant if a private pool were ever on the table.

## Candidate-by-candidate

| Candidate | Reachable from a public runner? | What Spacelift would add | Better free option |
|---|---|---|---|
| **UniFi → OpenTofu** (`ubiquiti-community/unifi`) | **No.** The controller is LAN-only | Nothing on free; it needs a private worker (Business) | OpenTofu + GitHub Actions **self-hosted runner** on the cluster/Beelink (outbound-only, same shape as a Spacelift private worker, $0). Biggest real gap in the lab, since the UDM firewall/IPv6-DNS blackout config only lives in `unifi-ops` SKILL.md today |
| **Beelink Ansible** | **No.** SSH to 192.168.1.70 | Nothing on free. Even paid, it duplicates `deploy-ai-stack.sh` + systemd-timer git-pull, and secrets would move from `op://` resolution into Spacelift env | Keep as is |
| **Cloudflare tunnels** | n/a | Nothing. Tunnel ingress is already a locally-managed `config.yaml` in this repo (`clusters/pi-k3s/cloudflare-tunnel/`), so it's already GitOps | Keep as is |
| **Cloudflare DNS records** | Yes (public API) | PR plan + confirm. But it needs a Cloudflare token stored in Spacelift, and the free tier has no policy gate | OpenTofu + GH Actions using the existing DNS-only token from 1Password (`reference_cloudflare_token_scope`: DNS edit only, which fits) |
| **GitHub repo settings / branch protection** | Yes | PR plan + confirm. But it needs a GitHub admin token held by the SaaS, and the App itself gets write on checks/PRs/webhooks | OpenTofu `integrations/github` in Actions. Today protection is a hand `gh api PUT` (`docs/flux-gitops.md` §Branch protection), so codifying it is worth doing, just not here |
| **Anything K3s** | No (LAN API) | Redundant. Flux already reconciles continuously, and has image automation, the drift gate and review-hub. Spacelift's k8s support is kubectl-in-a-run, which is a step backwards from a pull-based controller | Flux (and tofu-controller if Tofu ever needs to live in-cluster) |

### Free alternatives compared

- **OpenTofu + GitHub Actions + self-hosted runner.** The best fit. The runner is outbound-only (same network shape as a Spacelift private worker). PR plan comments, an `environment:` required reviewer as the human checkpoint, creds pulled from 1Password per job, state in a local backend (QNAP S3/MinIO or the K3s `kubernetes` backend). Zero new vendors.
- **Flux tofu-controller.** Fits the GitOps-pull model already in use, and plans/applies from inside the cluster, so it reaches UniFi. The downside is that its plan-approval UX is weaker than PR comments, and the project's maintenance cadence has been uneven. Second choice for UniFi if you want "Flux does everything".
- **Atlantis / Terrakube.** Self-hosted PR automation. They need inbound webhooks (another Cloudflare tunnel route) and another service to run. Overkill for one or two stacks.

## Security and fit

- **The control plane sees:** run logs (uploaded to Spacelift S3), plan output, state if Spacelift-managed, and env vars and secrets stored in Spacelift ("extra encrypted at rest"). With a private worker, secrets can be mounted from the worker (`SPACELIFT_WORKER_EXTRA_MOUNTS`, `SPACELIFT_MASK_ENVS`), but that's Business+.
- **GitHub App:** repo-scoped install is possible. It gets Checks/Statuses/Deployments/PRs/Webhooks R/W and Contents read. A self-created App is supported.
- **Private worker → LAN:** outbound-only (MQTT now, HTTPS long-poll later) with no inbound ports, so it would fit behind the UDM. But not on free.
- **PR-to-publish / human checkpoint:** compatible *in principle* (autodeploy off → confirm), but the checkpoint moves out of GitHub into Spacelift's UI. On free there's no approval policy to enforce "who" or "how many", so anyone with stack write can confirm.
- **No standing AI-held creds:** neutral to negative. The creds are held by a third party rather than an AI, but they're still standing, and the 1 free API key would tempt wiring agents to it.
- **Lock-in / cost cliff:** state is exportable and stacks are plain OpenTofu, so lock-in is low. The cliff is steep, though: $0 → $399/mo annual for 2 *public* workers, and the features that matter here (private workers, drift) need Business with no list price.

## Best single pilot

**None on Spacelift.** If you want one IaC pilot, do **UniFi under OpenTofu with a GitHub Actions self-hosted runner** (or tofu-controller), with state on the QNAP. It codifies the most fragile non-GitOps config in the lab, and it's the exact workload Spacelift free *can't* run.

## Hands-on test that would change the answer

Only one: create a free account and check (a) whether Free actually gets a public worker and at what concurrency, and (b) whether a private worker pool can be registered at all. If (b) were yes, the UniFi case would reopen. **Needs Matt's OK** (account creation + terms + GitHub App grant), so I haven't done it. My recommendation is not to, because the docs gate private workers to Business explicitly.

## Open questions

- Does Matt want UniFi under IaC at all, given that the MCP and `unifi-ops` is the current workflow? This decides whether any of this matters.
- Where should Tofu state live? QNAP S3-compatible bucket vs the K3s `kubernetes` backend (which sits inside the thing it might manage).
- Should branch protection (currently a hand `gh api` call) become code? Note the deliberate force-push-only rule for Flux image automation.

## Sources (read 2026-11-18)

spacelift.io/pricing · docs.spacelift.io: concepts/worker-pools, worker-pools/docker-based-workers, concepts/policy, concepts/policy/approval-policy, concepts/stack/drift-detection, concepts/run/tracked, integrations/source-control/github, vendors/terraform/state-management, vendors/terraform/external-state-access, vendors/opentofu, vendors/ansible/getting-started, vendors/kubernetes, product/security, product/billing/usage, concepts/stack/stack-settings.
