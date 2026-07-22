# Spec: the harness can farm work for any repo, not just pi-cluster

## 1. Why · [R]

The local executor's whole value proposition is that it is free, local, and always on — so it
should be able to take work for *any* project. It cannot. `harness run` hardcodes `pi-cluster`,
and qwen physically cannot hold a second repository.

This is not a theoretical limit. It has already bent a design decision: `specs/pulse-live-feed`
was deliberately scoped to one file in one repo **because the executor could not have touched
the collector in `beelink-ansible` even though that is where half the problem lives**. A tooling
constraint quietly became an architectural one, which is the expensive kind of debt.

The bias is also invisible from the outside. "Farm this out" reads as general; it silently means
"farm out pi-cluster work."

## 2. Outcomes (Definition of Done) · [R]

- `harness run <agent> <spec> --repo <name>` runs that spec against that repository, for every
  agent, with no manual preparation on the box.
- A repo the container has never seen is cloned on demand. No human SSHes in to `git clone`.
- Omitting `--repo` behaves exactly as today (`pi-cluster`), so nothing that currently works
  breaks.
- Adding a new project is a **config** change (one PAT scope entry), never a new credential.

## 3. Entities · [E]

| Entity | Meaning |
|---|---|
| `repo` | a bare repository name, e.g. `beelink-ansible`. Never a URL, never a path. |
| `HARNESS_REPO_OWNER` | GitHub owner used to build a clone URL. Default `mtgibbs`. |
| `BASE` | the container-side clone for `repo` |
| `TASK_DIR` | the per-run git worktree the loop actually executes in |

## 4. Approach · [A]

Make `repo` a first-class positional argument everywhere, and make **clone-on-demand** the
default behaviour instead of an error message telling a human to do it by hand.

Three of the four containers are already 90% there and were built for this — the work is mostly
removing a hardcode and bringing qwen in line.

## 5. Scope · [S]

### In scope (this repo, this spec's `tasks.txt`)
- `scripts/harness` — the laptop-side wrapper.

### Out of scope here, but REQUIRED — see §6 sequencing
- `files/coding-harness-*/run-task.sh` in **`beelink-ansible`**. Companion change, must land and
  deploy **first**. Tracked as a separate spec in that repo.

### Out of scope entirely
- The GitHub App / PAT itself. Widening the PAT's repo scope is a 1Password + GitHub settings
  action for a human, not code.

## 6. Prior decisions / facts the implementer must know · [S]

**Surveyed 2026-07-22 — these are real, verify before changing.**

The four containers do **not** share a signature today:

| container | `run-task.sh` args | clone location | clones on demand? |
|---|---|---|---|
| `coding-harness-qwen` | `<spec> [branch] [base]` — **3, no repo** | `$WORKSPACE/${HARNESS_REPO_NAME:-pi-cluster}` | at **boot only**, one repo, by `entrypoint.sh` |
| `coding-harness-claude` | `<spec> [repo] [branch] [base]` — **4** | `/Users/mtgibbs/dev/$REPO_NAME` | **no** — errors "clone it first" |
| `coding-harness-claude-2` | same as claude | same | no |
| `coding-harness-codex` | same as claude | same | no |

`scripts/harness` already papers over the mismatch and pins the repo:

```sh
if [ "$target" = "claude" ] || [ "$target" = "claude2" ] || [ "$target" = "codex" ]; then
  task_cmd="/usr/local/bin/run-task.sh $spec pi-cluster $branch $base_branch"
else
  task_cmd="/usr/local/bin/run-task.sh $spec $branch $base_branch"
fi
```

- Credentials are already in place and repo-agnostic: `entrypoint.sh` writes
  `~/.git-credentials` from `HARNESS_GITHUB_PAT`, so `git clone https://github.com/<owner>/<repo>`
  authenticates with no token in the URL. A new repo needs **no new credential** — only that the
  fine-grained PAT's repo list includes it.
- `branch` is generated laptop-side on purpose so every positional argument is a plain token —
  it sidesteps nested quoting through `ssh` + `tmux send-keys`. Keep that property.

### WORKED EXAMPLE — copy this shape

Two executors have now written a `--repo` parser here and **both were wrong**: one worked only
when the flag came first; the other never set `repo` at all and placed its parsing after
`target=`, where the criterion could not even be checked. Prose was not enough, so the shape is
given.

Write these two functions. They read **only their arguments**, so the gate can lift them out and
run them wherever in the file you put them:

```sh
# prints the --repo value, or nothing when the flag is absent
harness_repo_flag() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --repo)   printf '%s' "${2:-}"; return 0 ;;
      --repo=*) printf '%s' "${1#--repo=}"; return 0 ;;
      *)        shift ;;
    esac
  done
}

# prints the arguments with any --repo pair removed, one per line
harness_strip_repo() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --repo)   shift 2 || shift ;;
      --repo=*) shift ;;
      *)        printf '%s\n' "$1"; shift ;;
    esac
  done
}
```

Use them like this, before `target=` and `spec=` are assigned:

```sh
repo="$(harness_repo_flag "$@")"
set -- $(harness_strip_repo "$@")
```

The unquoted `$(...)` is deliberate, not an oversight. Every positional this script handles is a
plain token with no spaces — it has to survive `ssh` + `tmux send-keys` (see Norms) — so word
splitting is exactly the behaviour wanted. Do **not** "fix" it by quoting; that collapses every
argument into one.

### Why `--repo` is APPENDED as a flag, not passed as positional 2

The first draft of this spec said "pass repo in position 2 for every agent". That is wrong, and
the companion spec (`beelink-ansible`) is where it surfaced.

qwen's `run-task.sh` takes **3** positionals: `<spec> <branch> <base>`. Passing repo in position
2 would mean that, in the window between the container half deploying and this merging, **the
branch name is read as a repo name** — it does not error, it tries to clone
`github.com/mtgibbs/ralph-<spec>-1784…` and reports something unrelated.

Appending `--repo <name>` shifts nothing. Every positional keeps its meaning in every container,
in both directions:

| | old `run-task.sh` | new `run-task.sh` |
|---|---|---|
| **old `harness`** (no flag) | today's behaviour | today's behaviour |
| **new `harness`**, no flag | today's behaviour | today's behaviour |
| **new `harness`** `--repo x` | flag ignored → wrong repo, **loudly** | correct |

So deploy order stops mattering, and the one remaining bad cell fails visibly rather than
silently. A sequencing hazard you can delete beats one you document.

## 7. Norms · [N]

- POSIX-ish bash matching the existing file. No new dependencies.
- Every positional passed through `ssh` + `tmux send-keys` stays a plain token — no spaces, no
  quotes, no shell metacharacters.
- Error messages name the fix, not just the fault (the file's existing voice).

## 8. Safeguards · [S]

1. **Backward compatible.** `harness run qwen specs/foo` with no `--repo` produces exactly the
   command it produces today.
2. **`repo` is validated as a bare name** — `^[A-Za-z0-9._-]+$`. It is interpolated into a
   remote command; a value with a slash, space, quote or `;` must be rejected before it is sent,
   not escaped after.
3. **No credential in any URL or log line.** Clone URLs are `https://github.com/<owner>/<repo>`;
   auth comes from the credential store the entrypoint already wrote.

## 9. Task breakdown · [O]

See `tasks.txt` — three tasks, all in `scripts/harness`.

Companion tasks in `beelink-ansible` (separate spec, must deploy first):
- qwen's `run-task.sh` adopts the 4-arg signature `<spec> [repo] [branch] [base]`.
- All four `run-task.sh` clone `$BASE` on demand when it is not a git clone, using
  `https://github.com/${HARNESS_REPO_OWNER:-mtgibbs}/$REPO_NAME`.

> **Farming that half out is now possible and is a good first proof:** the claude/codex
> containers already resolve `BASE` from `/Users/mtgibbs/dev/<repo>`, so cloning
> `beelink-ansible` into one of their mirrors lets *that* agent do the beelink work — using
> exactly the capability this spec generalises.

## 10. Acceptance criteria (EARS) · [O]

1. **Where** `--repo <name>` is absent, `harness run` **shall** emit the same command string it
   emits today (`pi-cluster` for the workstation containers, no repo token for qwen).
2. **When** `--repo <name>` is supplied, `harness run` **shall** APPEND `--repo <name>` to the
   remote command, leaving every existing positional in place and unshifted.
3. **Where** `<name>` does not match `^[A-Za-z0-9._-]+$`, `harness run` **shall** exit non-zero
   with a message naming the offending value, and **shall not** contact the host.
4. **When** `--repo` is supplied, the usage/echo line **shall** state which repo the run targets,
   so the operator can see it was honoured.
5. **Where** `--repo` appears in any argument position, `harness run` **shall** parse it
   identically (flag order must not matter).

## 11. Verification (the harness)

`./specs/harness-multi-repo/verify.sh` — STATIC, offline, presence-gated.

LIVE tier — human, after the `beelink-ansible` half is deployed:
- `harness run codex specs/<something> --repo beelink-ansible` clones and runs in the right repo.
- `harness run qwen specs/<something>` (no flag) behaves exactly as before.

## 12. Open questions

- Should a repo the PAT cannot reach fail loudly at `harness run` time (a pre-flight `git
  ls-remote`) rather than 30 seconds later inside the container? Cheap, and it turns a confusing
  in-container clone failure into an immediate, actionable one. Deferred — decide at review.
