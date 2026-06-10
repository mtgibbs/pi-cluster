#!/usr/bin/env python3
"""review-hub reporting — three surfaces, one source of truth.

  - per-validator Check Run  : the merge gate + the pipeline view (each independent,
                               so a build-flow diagram shows exactly who blocked).
  - ONE report-card comment  : the roster at a glance, links to each validator's
                               docs, findings for any blocker. Edits in place.
  - inline review comments   : iteration 2 — pointers on the offending line.

`summarize()` flattens a validator's `(results, any_block, body)` into a uniform
dict; `render_report()` builds the single comment; `check_title/summary()` enrich
each Check Run so clicking a red check explains itself.
"""
import os

# The validators live in pi-cluster; their contract.md IS the human-readable spec
# of what each one checks. Overridable if the docs ever move to a friendlier page.
DOCS_BASE = os.environ.get(
    "REVIEW_HUB_DOCS_BASE",
    "https://github.com/mtgibbs/pi-cluster/blob/main/specs/validators")
REPORT_MARKER = "<!-- review-hub:report -->"

# The single always-on Check Run. It is posted for EVERY PR in an opted-in repo —
# even when no validator applies — so branch protection can require ONE stable check
# by name without wedging PRs that don't touch a watched file. The per-validator
# checks stay (they carry the detail + the pipeline view); THIS is the one you
# require in branch protection to make the gates HARD.
ROLLUP_CHECK = os.environ.get("REVIEW_HUB_ROLLUP_NAME", "review-hub")

_ICON = {"pass": "✅", "block": "🔴", "neutral": "⚪", "error": "💥"}
_ORDER = {"block": 0, "error": 1, "pass": 2, "neutral": 3}


def docs_url(name):
    return f"{DOCS_BASE}/{name}/contract.md"


def summarize(name, concern, results, any_block, body):
    """One validator's outcome, normalized across validator shapes.
    state: block (fail/flag) · pass · neutral (no matching change) · error (crashed)."""
    results = results or []
    votes, findings = [], []
    for r in results:
        if isinstance(r, dict):
            votes = votes or list(r.get("runs") or [])
            findings += list(r.get("findings") or [])
    state = "neutral" if body is None else ("block" if any_block else "pass")
    seen = set()  # multi-vote aggregation repeats the same finding per rep — dedupe, keep order
    findings = [f for f in findings if not (f in seen or seen.add(f))]
    return {
        "name": name, "concern": concern, "state": state,
        "votes": votes,
        "n_total": len(votes),
        "n_escalating": sum(1 for v in votes if v != "pass"),
        "findings": findings[:6],
    }


def error_summary(name, concern, err):
    return {"name": name, "concern": concern, "state": "error", "votes": [],
            "n_total": 0, "n_escalating": 0, "findings": [str(err)[:200]]}


def _result_text(s):
    if s["state"] == "pass":
        return "passed" + (f" · {s['n_total']}/{s['n_total']} clear" if s["n_total"] else "")
    if s["state"] == "block":
        tally = f" · {s['n_escalating']}/{s['n_total']} flagged" if s["n_total"] else ""
        return f"**needs review**{tally}"
    if s["state"] == "neutral":
        return "n/a — no matching change"
    return "**error** — review manually"


def render_report(summaries, files, version):
    """The single report-card comment. Marker first so it upserts in place."""
    summaries = sorted(summaries, key=lambda s: (_ORDER.get(s["state"], 9), s["name"]))
    blockers = [s for s in summaries if s["state"] in ("block", "error")]
    n = len(summaries)
    headline = (f"🚫 {len(blockers)} of {n} need review" if blockers
                else f"✅ all {n} passed")

    out = [REPORT_MARKER, f"## 🛡️ review-hub — {headline}", ""]
    out += ["| | Validator | Result | Checks for |", "|--|--|--|--|"]
    for s in summaries:
        link = f"[{s['name']}]({docs_url(s['name'])})"
        out.append(f"| {_ICON.get(s['state'], '•')} | {link} | {_result_text(s)} | {s['concern']} |")
    out.append("")

    if blockers:
        out += ["> [!CAUTION]",
                f"> **{len(blockers)} check(s) need a human** before merge. "
                "The `review-hub` gate stays red until each is resolved.", ""]
        for s in blockers:
            out.append(f"**🔴 {s['name']}** — {s['concern']}")
            if s["state"] == "error":
                out.append("- crashed during review — look at this change manually")
            out += [f"- {f}" for f in s["findings"]] or ["- (no detail — see the check)"]
            out.append("")

    filetxt = ", ".join(f"`{f}`" for f in files[:8]) or "—"
    more = f" +{len(files) - 8} more" if len(files) > 8 else ""
    out.append(f"<sub>reviewed {filetxt}{more} · the required gate is the single "
               f"`{ROLLUP_CHECK}` check; the per-validator checks above carry the detail "
               f"· review-hub {version}</sub>")
    return "\n".join(out)


# ---- per-validator Check Run output (what they see clicking the check) ----
_TITLE = {"block": "Human review required", "pass": "All clear",
          "neutral": "No applicable changes", "error": "Validator error"}


def check_title(s):
    return _TITLE.get(s["state"], "Reviewed")


def check_summary(s):
    parts = [f"**Checks:** {s['concern']}", ""]
    if s["state"] == "block":
        parts.append("**Findings**")
        parts += [f"- {f}" for f in s["findings"]] or ["- (see the review-hub report comment)"]
    elif s["state"] == "pass":
        parts.append("No issue found in the changed files.")
    elif s["state"] == "neutral":
        parts.append("No file in this PR matched this validator.")
    else:
        parts.append("This validator crashed — a human must review the change.")
    parts += ["", f"📖 [What this validator checks]({docs_url(s['name'])})"]
    return "\n".join(parts)


# ---- the rollup: ONE always-on required Check Run ----
def _rollup_body(summaries, lead):
    summaries = sorted(summaries, key=lambda s: (_ORDER.get(s["state"], 9), s["name"]))
    out = [lead, ""]
    if summaries:
        out += ["| | Validator | Result |", "|--|--|--|"]
        for s in summaries:
            link = f"[{s['name']}]({docs_url(s['name'])})"
            out.append(f"| {_ICON.get(s['state'], '•')} | {link} | {_result_text(s)} |")
    out += ["", f"<sub>`{ROLLUP_CHECK}` rollup — the single required check. The "
            "per-validator checks carry the detail; the report-card comment lists "
            "every finding.</sub>"]
    return "\n".join(out)


def rollup(summaries):
    """Collapse every validator's outcome into the ONE `review-hub` Check Run.

    Concludes `failure` iff any validator escalated (`block`) or crashed (`error`);
    `success` otherwise — INCLUDING the empty roster (nothing matched = nothing to
    gate = a pass). Always `success`/`failure`, never `neutral`: a required check
    must conclude `success` to clear branch protection, and `neutral`'s treatment is
    ambiguous, so the clean case is unambiguously `success`.

    Returns {conclusion, title, summary} for forge.complete_check_run."""
    blockers = [s for s in summaries if s["state"] in ("block", "error")]
    n = len(summaries)
    if not summaries:
        return {"conclusion": "success", "title": "No applicable gates",
                "summary": _rollup_body(
                    [], "No changed file matched an opted-in validator — nothing to review.")}
    if blockers:
        return {"conclusion": "failure", "title": f"{len(blockers)} of {n} need review",
                "summary": _rollup_body(
                    summaries,
                    f"**{len(blockers)} of {n}** validator(s) need a human before merge. "
                    "Open each red check (or the report-card comment) for the findings.")}
    return {"conclusion": "success", "title": f"All {n} passed",
            "summary": _rollup_body(
                summaries, f"All **{n}** applicable validator(s) passed — nothing needs a human.")}
