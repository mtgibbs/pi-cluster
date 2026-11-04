"""An errored vote blocks like a flag, so its reason must reach the report.

Regression for pi-cluster-mcp#57: read-only-integrity blocked "5/5 flagged" with no findings,
because every vote errored (the model rambled past max_tokens, or timed out) and aggregate()
only kept findings from fail/flag votes.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "reviewhub"))
import reporting  # noqa: E402
import triggerable_judge as tj  # noqa: E402

VALIDATORS = [
    "concurrency_safety", "dependency_update", "fail_closed", "gate_regression", "input_validation",
    "mutation_gating", "no_false_green", "output_bounds", "read_only_integrity", "secret_hygiene",
]


class TestNoMarkersReason:
    def test_transport_error_keeps_its_text(self):
        assert "TimeoutError" in tj.no_markers_reason("ERROR: TimeoutError: timed out")
        assert "HTTP 500" in tj.no_markers_reason("HTTP 500: upstream")

    def test_reply_cut_off_at_max_tokens(self):
        reason = tj.no_markers_reason("Then why fail? So no violation.\n" + tj.TRUNCATED_NOTE)
        assert "max_tokens" in reason

    def test_plain_missing_markers_says_how_long_the_reply_was(self):
        assert "12-char reply" in tj.no_markers_reason("no json here")


@pytest.mark.parametrize("name", VALIDATORS)
class TestEveryValidator:
    def mod(self, name):
        return importlib.import_module(f"validators.{name}")

    def test_parse_reports_why_there_is_no_verdict(self, name):
        res = self.mod(name).parse("ERROR: TimeoutError: timed out")
        assert res["verdict"] == "error"
        assert any("TimeoutError" in f for f in res["findings"])

    def test_all_errored_votes_block_with_their_reason(self, name):
        m = self.mod(name)
        agg = m.aggregate([m.parse(f"rambling\n{tj.TRUNCATED_NOTE}") for _ in range(5)])
        assert agg["verdict"] != "pass"
        assert agg["findings"], "an errored-vote block must say why"
        assert any("max_tokens" in f for f in agg["findings"])

    def test_real_findings_come_before_error_reasons(self, name):
        m = self.mod(name)
        flag = {"verdict": "flag", "findings": ["real problem"], "gate": "label"}  # gate: gate_regression only
        err = m.parse("ERROR: TimeoutError: timed out")
        assert m.aggregate([flag, flag, err, err, err])["findings"][0] == "real problem"


class TestReportTally:
    def summary(self, votes):
        return reporting.summarize("x", "c", [{"runs": votes, "findings": ["f"]}], True, "body")

    def test_errored_votes_are_not_called_flagged(self):
        assert reporting._result_text(self.summary(["error"] * 5)).endswith("· 5/5 errored")

    def test_mixed_tally(self):
        text = reporting._result_text(self.summary(["flag", "flag", "error", "pass", "pass"]))
        assert text.endswith("· 2/5 flagged, 1/5 errored")

    def test_all_flagged_unchanged(self):
        assert reporting._result_text(self.summary(["fail"] * 5)).endswith("· 5/5 flagged")
