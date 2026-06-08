"""Evaluator registry — the framework seam for "many evaluators, many repos".

An evaluator = a contract + a selector + which repos it applies to. The receiver
asks `evaluators_for(repo)` and runs each. Adding a new gate (e.g. an MCP
tool-safety reviewer on pi-cluster-mcp) is a new Evaluator subclass here — NOT a
new credential, runner, or service.
"""
import sys
from pathlib import Path

# triggerable_judge.py lives one level up (scripts/); it carries the reusable
# engine (judge/aggregate/render) + the triggerable selector for now.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import triggerable_judge as tj  # noqa: E402


class Evaluator:
    name = "evaluator"
    check_name = "evaluator"

    def applies(self, repo):
        raise NotImplementedError

    def review(self, forge, reps, timeout, model, raw_dir):
        """Return (results, any_block, body). body is None when nothing applies."""
        raise NotImplementedError


class TriggerableEvaluator(Evaluator):
    """Evaluator #1: changed CronJobs claiming homelab.mcp/triggerable, on the
    GitOps repo, judged against the triggerable contract."""

    name = "triggerable-judge"
    check_name = "triggerable-judge"
    repos = {"mtgibbs/pi-cluster"}

    def applies(self, repo):
        return repo in self.repos

    def review(self, forge, reps, timeout, model, raw_dir):
        targets = tj.select_triggerable_targets(forge)
        if not targets:
            return [], False, None
        results, any_block = tj.judge_targets(
            targets, reps, timeout, "litellm", model, raw_dir)
        return results, any_block, tj.render_review(results, any_block)


# Evaluator #2 (future): an MCP tool-safety reviewer on mtgibbs/pi-cluster-mcp —
# checks that a new/changed triggerable tool keeps the label gate + concurrency
# guard. Same engine + forge + App; just a different selector + contract.

REGISTRY = [TriggerableEvaluator()]


def evaluators_for(repo):
    return [e for e in REGISTRY if e.applies(repo)]
