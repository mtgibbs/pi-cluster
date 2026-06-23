# Spec: Resilient postgres-backup (skip parked DBs, never lose the others)

- **Status:** Planned v0.1 (OQs resolved)
- **Owner:** Matt (orchestrated by Claude; executed by the local Q8 coder)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml` (the inline `command` shell script only)

---

## 1. Why · [R — Requirements]

The weekly `postgres-backup` CronJob dumps **two** databases in sequence under `set -e`:
Immich first, then n8n. Immich was **parked** (deployment scaled to `0/0`) during the streaming
investigation, so `pg_dump -h immich-postgresql.immich.svc.cluster.local` now fails — and because
of `set -e`, the whole job aborts **before it ever reaches the n8n dump**. Result: the 2026-06-21
run failed (alerting Discord), and **n8n has had no DB backup since**. One parked, intentionally-down
database must not take down the backup of every other database.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. The job backs up **every reachable** Postgres target (today: n8n) even when another (Immich) is parked.
2. A parked/unreachable target is **logged as SKIPPED** and does **not** fail the job.
3. A **reachable** target whose dump or transfer fails **does** fail the job (a green job still means
   "every reachable DB was backed up" — we never silently lose a backup).
4. When Immich is later un-parked, it is backed up again automatically — no manifest change needed.
5. Nothing else about the backup changes: same NAS path layout, same SSH/rsync, same dump format,
   same secrets, same schedule.

## 3. Entities · [E — Entities]

**Backup targets** (the list the script iterates). Each target = `(name, host, user, db, password_env)`:

| name | host | user | db | password env | live state |
|---|---|---|---|---|---|
| `immich` | `immich-postgresql.immich.svc.cluster.local` | `immich` | `immich` | `DB_PASSWORD` | **PARKED (deploy 0/0)** |
| `n8n` | `n8n-postgresql.n8n.svc.cluster.local` | `n8n` | `n8n` | `N8N_DB_PASSWORD` | running (1/1) |

Dump artifact path on the NAS (unchanged): `${NAS_PATH}/${BACKUP_DATE}/postgres/<name>-postgres.dump`
where `NAS_PATH=/share/cluster/backups`, `BACKUP_DATE=$(date +%Y-%m-%d)`.

## 4. Approach · [A — Approach]

Refactor the inline `command` script so the two hardcoded dump blocks become **one loop over the two
targets**, each guarded by a `pg_isready` reachability precheck. Replace the script-wide `set -e`
(which is what couples the targets) with **explicit per-target error handling** that tracks a failure
count and exits non-zero only if a *reachable* target failed. Keep everything else byte-for-byte where
possible. Mirror the existing in-script conventions (the `echo "--- Backing up: X ---"` logging, the
`rsync -avz -e "ssh -i ... -o StrictHostKeyChecking=no"` transfer, the dated NAS dir creation).
Rejected: deleting the Immich block outright — Immich may be un-parked later, so a runtime skip
(self-healing) beats a static removal.

## 5. Scope · [S — Structure: boundary]

### In scope
- The inline `command:` shell script in `clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml`.

### Out of scope
- **Do NOT** change the CronJob `schedule`, `concurrencyPolicy`, history limits, `backoffLimit`,
  `serviceAccountName`, `image`, `resources`, `env:`, `volumes:`, or `volumeMounts:`.
- **Do NOT** change the secret references (`immich-db-password`, `n8n-db-password`) or the SSH key secret.
- **Do NOT** touch any other file in `backup-jobs/` (pvc/media/worker2/unifi/git-mirror jobs, kustomization).
- **Do NOT** un-park Immich or change anything in the `immich` namespace (that's a separate decision).
- **Do NOT** change the NAS path layout or the dump filename scheme beyond making `<name>` a variable.

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- **Confirmed root cause (live):** `kubectl get deploy -n immich` → `immich-postgresql 0/0`. The Immich
  Postgres service has no endpoints, so a connect hangs/fails. n8n Postgres is `1/1` and healthy.
- **The image is `instrumentisto/rsync-ssh:alpine`** and the script already runs
  `apk add --no-cache postgresql16-client` — that package provides **both `pg_dump` and `pg_isready`**.
  No new package is needed.
- **The container shell is BusyBox `ash`** (Alpine `/bin/sh`), **NOT bash.** Bash-only constructs FAIL
  at runtime. In particular **`${!var}` (indirect expansion) is unsupported** — do NOT use it to resolve
  a password from an env-var *name*. Instead **pass the password value as a function argument**:
  `backup_one immich <host> immich immich "$DB_PASSWORD"` → inside, `PGPASSWORD="$5"`. (`local` IS
  supported by ash, so a `backup_one()` function with `local` vars is fine.)
- **`pg_isready`** returns exit `0` when the server is accepting connections, non-zero otherwise; with
  `-t 5` it bounds the wait to 5s. It does not need a password (it only probes connectivity). Use it as
  the reachability gate per target. (A parked DB → no endpoint → `pg_isready` fails within 5s.)
- **`pg_dump` hang guard:** pass `connect_timeout=10` via the connection (e.g. `-d "dbname=<db> connect_timeout=10"`
  or `PGCONNECT_TIMEOUT=10`) so a half-up DB fails fast instead of hanging the pod.
- **Secrets are already injected** as env: `DB_PASSWORD` (immich, from secret `immich-db-password`)
  and `N8N_DB_PASSWORD` (n8n, from secret `n8n-db-password`). Reference them via `PGPASSWORD` exactly as
  today. **Never inline a password.**
- **Existing in-script conventions to keep** (copy them): the `BACKUP_DATE`/`NAS_*`/`SSH_KEY` setup,
  `cp ${SSH_KEY} /tmp/id_ed25519 && chmod 600`, the `ssh ... "mkdir -p ${NAS_PATH}/${BACKUP_DATE}/postgres"`,
  `--format=custom --compress=9`, the `rsync -avz -e "ssh -i /tmp/id_ed25519 -o StrictHostKeyChecking=no"`,
  and the final `ls -lh` summary + `rm -f` cleanup.
- **Operational reality:** this is GitOps — the change is a committed YAML edit; Flux applies it. The job
  is weekly (Sun 02:30). We will NOT wait a week to validate — verify is static (see §11).

## 7. Norms · [N — Norms]

- **BusyBox `ash`** (the container shell), matching the current script. No bash-only constructs —
  **never `${!var}` indirect expansion** and **never `<<<` here-strings** (resolve passwords by
  arg-passing, see §6). `local` is OK.
- **Count INSIDE the function.** `backup_target()` runs in the current shell (not a subshell), so it
  can increment the parent's `backed_up` / `skipped` / `failed` counters directly — and only the
  function knows which of the three outcomes occurred. Do NOT try to infer skip-vs-success from the
  function's return code in the caller (that's how the broken `grep "SKIPPED" <<< ...` hack arose). The
  caller just invokes the two targets as plain statements.
- **Do NOT suppress `pg_dump`/`rsync` stderr** (no `> /dev/null 2>&1` on them) — a backup failure MUST be
  diagnosable in the job log. An explicit `echo "FAILED: ..."` is fine *in addition to*, not instead of,
  their real stderr.
- **Logging:** keep the `--- Backing up: <name> ---` header style; add an explicit
  `--- SKIPPED: <name> (unreachable) ---` line for a parked target, and a one-line final summary stating
  how many were backed up / skipped / failed. The human (and the future backup-watcher) reads these lines.
- **Error handling is the whole point:** a single target's failure must be *contained*. Prefer a small
  `backup_one()` function over copy-pasted blocks, looped over the target list.
- **Determinism:** target list is explicit and ordered (immich, n8n) — do not auto-discover DBs.

## 8. Safeguards · [S — Safeguards]

- **No inline secrets** — passwords come only from `DB_PASSWORD` / `N8N_DB_PASSWORD` env. (verify: §11)
- **A green job ⇒ every reachable DB was dumped.** If a *reachable* target's `pg_dump`/`rsync` fails, the
  job MUST exit non-zero. Skips (unreachable) are not failures. (verify: §11 asserts the failure-count exit)
- **n8n must still be backed up** — its host/secret references must remain. (verify: §11)
- **Non-destructive** — the job only writes new dated dumps to the NAS; no deletes, no overwrites of other
  dates. Keep it that way.
- **NAS path layout unchanged** — restores depend on `${NAS_PATH}/${BACKUP_DATE}/postgres/`. (verify: §11)

## 9. Task breakdown · [O — Operations]

Single bounded task (one file, one self-contained script). T1: rewrite the inline `command` script to
loop over the (immich, n8n) targets with a `pg_isready` gate, `connect_timeout=10` dump, contained
per-target failure handling, and a non-zero exit iff a reachable target failed. Everything outside the
`command:` block stays identical.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **A1 (Ubiquitous):** The job shall attempt each configured target in order: `immich`, then `n8n`.
- **A2 (Event):** When a target's `pg_isready -t 5` succeeds, the job shall `pg_dump` it (custom format,
  compress 9, `connect_timeout=10`) and `rsync` the dump to `${NAS_PATH}/${BACKUP_DATE}/postgres/`.
- **A3 (Unwanted):** If a target's `pg_isready` fails, then the job shall log `SKIPPED: <name>` and
  continue to the next target **without** failing the job.
- **A4 (Unwanted):** If a *reachable* target's `pg_dump` or `rsync` fails, then the job shall record a
  failure and **exit non-zero** after attempting the remaining targets.
- **A5 (State-driven):** While every reachable target succeeded, the job shall exit `0` even if one or
  more targets were skipped.
- **A6 (Ubiquitous):** The job shall contain no inline secret; `PGPASSWORD` is set only from the existing
  `DB_PASSWORD` / `N8N_DB_PASSWORD` env vars.
- **A7 (Ubiquitous):** Every `pg_dump` connection shall carry `connect_timeout=10`.

## 11. Verification (the harness) — `verify.sh`

STATIC, offline, deterministic (run from repo root). The gate asserts, against
`clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml`:
1. File is valid YAML and is a `CronJob` named `postgres-backup`.
2. Script contains `pg_isready` (A1–A3 reachability gate).
3. Script references BOTH `immich-postgresql.immich.svc.cluster.local` and
   `n8n-postgresql.n8n.svc.cluster.local` (A1; n8n not dropped).
4. Script contains a SKIP log token (`SKIP`) (A3).
5. Script contains `connect_timeout=10` (A7).
6. Script does NOT start the body with a bare `set -e` as the sole error strategy — assert presence of an
   explicit failure counter / non-zero exit (`exit 1` or `exit $`...) so a reachable failure still fails (A4).
7. Secrets intact: manifest still references `DB_PASSWORD`, `N8N_DB_PASSWORD`, `immich-db-password`,
   `n8n-db-password` (A6) and no obvious inline password (`PGPASSWORD=` followed by a literal that isn't a var).
8. NAS path layout token `${NAS_PATH}/${BACKUP_DATE}/postgres` (or `/postgres/`) still present.
9. `apk add` still installs `postgresql16-client`.

## 11b. Loop execution (handing to a local model)

Single task, single file → one-shot generation is appropriate. Because Immich's DB is parked, the
manifest cannot be live-tested this session; the static `verify.sh` is the gate. The model outputs the
complete corrected file; the orchestrator writes it and runs `verify.sh`. Model never self-certifies.

## 12. Open questions

- **OQ1 (resolved):** Is Immich parked deliberately? **Yes** — parked during the streaming investigation;
  keep it parked. Hence runtime-skip, not block removal.
- **OQ2 (resolved):** Does `pg_isready` ship in `postgresql16-client`? **Yes** (same package as `pg_dump`).

## 14. Tuning log

- **Round 1 (Q8):** used `${!password_env}` indirect expansion — bash-only, fails in BusyBox ash. Gate
  hardened (`${!` ban) + §6/§7 written back (pass the password value as an arg).
- **Round 2 (Q8):** added a broken skip-counter `grep -q "SKIPPED" <<< $(echo "---")` — a `<<<` here-string
  (ash-incompat) wrapping logic that never matches. Gate hardened (`<<<` ban) + §7/§9 written back (count
  INSIDE the function; the caller is plain statements).
- **Round 3 (Q8):** passed the 16-check gate; merged as PR #22. **Post-merge review caught a latent gap the
  gate missed:** the model edited *around* the leading `set -e` (its hunks started at line 45) and left it
  in. Harmless in the current config (immich is skipped → `return 0`; n8n is the last/only reachable target,
  so nothing is short-circuited), but it violates A4 ("attempt remaining targets") if immich is ever
  un-parked AND its dump fails. **Follow-up:** removed `set -e`; added a "no script-wide `set -e`" assertion
  to `verify.sh`. **Lesson:** a passing static gate can still be confidently wrong — a human eyeball of the
  full diff (not just the changed hunks) remains load-bearing for the autonomous loop.
