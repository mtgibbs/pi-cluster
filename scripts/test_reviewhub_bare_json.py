"""A reply that is nothing but the verdict JSON (markers dropped) is still that verdict.

Flash-Next omitted the BEGIN/END markers on 11 of 185 short replies in the 2026-11-12
reps=5 sweep; each counted as an errored (escalating) vote. The fallback accepts only a
reply that is entirely one JSON object — never JSON picked out of surrounding prose.
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "reviewhub"))
import triggerable_judge as tj  # noqa: E402

VALIDATORS = [
    "concurrency_safety", "fail_closed", "gate_regression", "input_validation",
    "mutation_gating", "no_false_green", "output_bounds", "read_only_integrity", "secret_hygiene",
]
BARE = '{"verdict": "fail", "findings": ["shell injection via domain"]}'


class TestVerdictBody:
    def test_markers_win(self):
        text = f"thinking {{\"verdict\": \"pass\"}}\n{tj.BEGIN}\n{BARE}\n{tj.END}"
        assert tj.verdict_body(text) == BARE

    def test_bare_object(self):
        assert tj.verdict_body(f"  {BARE}\n") == BARE

    def test_fenced_object(self):
        assert tj.verdict_body(f"```json\n{BARE}\n```") == BARE

    def test_json_inside_prose_is_not_a_verdict(self):
        assert tj.verdict_body(f"Example output: {BARE} — but I think it passes.") is None

    def test_truncated_reply_is_not_a_verdict(self):
        assert tj.verdict_body('{"verdict": "pass", "findings": [\n' + tj.TRUNCATED_NOTE) is None

    def test_non_object_json_is_not_a_verdict(self):
        assert tj.verdict_body('["fail"]') is None

    def test_none_and_empty(self):
        assert tj.verdict_body(None) is None
        assert tj.verdict_body("") is None


def test_parse_verdict_accepts_bare_json():
    res = tj.parse_verdict('{"verdict": "flag", "criteria": ["idempotent"], "findings": ["x"]}')
    assert res["ok"] and res["verdict"] == "flag" and res["criteria"] == ["idempotent"]


@pytest.mark.parametrize("name", VALIDATORS)
def test_validator_accepts_bare_json(name):
    res = importlib.import_module(f"validators.{name}").parse(BARE)
    assert res["verdict"] == "fail"
    assert res["findings"] == ["shell injection via domain"]


def test_dependency_update_accepts_bare_json():
    m = importlib.import_module("validators.dependency_update")
    assert m.parse('{"verdict": "flag", "findings": ["major bump"]}')["verdict"] == "flag"
