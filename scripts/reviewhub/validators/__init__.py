"""Validator roster — single-concern specialists.

The receiver asks `validators_for(repo, changed_files, opted_in)` and runs EVERY
one that applies, each posting its OWN check run. `opted_in` comes from the repo's
.review-hub.yml — a repo signs up for review by committing that file. Adding a
specialist = a class here; no new App, secret, or service. A validator does ONE
thing well (a narrow check beats a generalist — gate-regression: 1.00, one fix).
"""
import fnmatch
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))             # gate_regression (same package)
sys.path.insert(0, str(_HERE.parents[1]))  # scripts/ (triggerable_judge)

import triggerable_judge as tj  # noqa: E402
from gate_regression import GateRegressionValidator  # noqa: E402


def _matches(files, globs):
    return any(any(fnmatch.fnmatch(f, g) for g in globs) for f in files)


class TriggerableValidator:
    """Single-concern: does a changed CronJob deserve the triggerable label?"""

    # ---- routing config: `repos` = which repos this validator is VALID FOR
    #      (empty set = any repo); `globs` = which changed files it watches.
    #      A repo OPTS IN by listing this validator's name in its .review-hub.yml.
    name = "triggerable-judge"
    repos = {"mtgibbs/pi-cluster"}
    globs = ["clusters/*.yaml", "clusters/*.yml"]  # fnmatch: `*` spans `/`
    # -------------------------------------------------------------------------

    def applies_files(self, files):
        return _matches(files, self.globs)

    def review(self, forge, reps, timeout, model, raw_dir):
        targets = tj.select_triggerable_targets(forge)
        if not targets:
            return [], False, None
        results, any_block = tj.judge_targets(targets, reps, timeout, "litellm", model, raw_dir)
        return results, any_block, tj.render_review(results, any_block)


REGISTRY = [TriggerableValidator(), GateRegressionValidator()]


def validators_for(repo, files, opted_in):
    """The validators that run on this PR. Two-sided handshake:
      (1) the repo OPTED IN to it (.review-hub.yml lists its name),
      (2) the validator is VALID FOR this repo (repos empty = any),
      (3) the changed files match the validator's globs.
    """
    return [v for v in REGISTRY
            if v.name in opted_in
            and (not v.repos or repo in v.repos)
            and v.applies_files(files)]
