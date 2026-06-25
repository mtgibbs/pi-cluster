"""Unit tests for the dependency-update validator's pure (network-free) surface.

WORKED EXAMPLE / PATTERN for the other validators: test the five pure functions
— build_prompt, parse, aggregate, _render_pr, applies_files — and DO NOT touch
review() (it calls the LLM). No mocking needed. Imports resolve via conftest.py.
"""
import json

from dependency_update import (
    build_prompt, parse, aggregate, _render_pr,
    DependencyUpdateValidator, BEGIN, END,
)


def _verdict_text(verdict, findings=None):
    body = json.dumps({"verdict": verdict, "findings": findings or []})
    return f"some preamble\n{BEGIN}\n{body}\n{END}\ntrailing prose"


class TestAppliesFiles:
    def setup_method(self):
        self.v = DependencyUpdateValidator()

    def test_cluster_manifest_matches(self):
        assert self.v.applies_files(["clusters/pi-k3s/jellyfin/deployment.yaml"]) is True

    def test_package_lock_matches(self):
        assert self.v.applies_files(["package-lock.json"]) is True

    def test_nested_package_lock_matches(self):
        assert self.v.applies_files(["clusters/pi-k3s/family-board/package-lock.json"]) is True

    def test_go_mod_matches(self):
        assert self.v.applies_files(["go.mod"]) is True

    def test_dockerfile_matches(self):
        assert self.v.applies_files(["clusters/pi-k3s/x/Dockerfile"]) is True

    def test_workflow_matches(self):
        assert self.v.applies_files([".github/workflows/ci.yml"]) is True

    def test_unrelated_does_not_match(self):
        assert self.v.applies_files(["README.md", "docs/x.md"]) is False

    def test_empty_does_not_match(self):
        assert self.v.applies_files([]) is False


class TestParse:
    def test_pass(self):
        assert parse(_verdict_text("pass"))["verdict"] == "pass"

    def test_flag_with_findings(self):
        r = parse(_verdict_text("flag", ["major bump"]))
        assert r["verdict"] == "flag"
        assert r["findings"] == ["major bump"]

    def test_missing_markers_error(self):
        r = parse("no markers in this output")
        assert r["verdict"] == "error"
        assert "no verdict markers" in r["findings"][0]

    def test_bad_json_error(self):
        r = parse(f"{BEGIN}\n{{not valid json\n{END}")
        assert r["verdict"] == "error"
        assert "bad json" in r["findings"][0]

    def test_bad_verdict_error(self):
        # "fail" is not a dependency-update verdict (only pass|flag)
        r = parse(_verdict_text("fail"))
        assert r["verdict"] == "error"
        assert "bad verdict" in r["findings"][0]

    def test_last_marker_pair_wins(self):
        t = (f"{BEGIN}\n{json.dumps({'verdict': 'pass'})}\n{END}\n"
             f"{BEGIN}\n{json.dumps({'verdict': 'flag', 'findings': ['x']})}\n{END}")
        assert parse(t)["verdict"] == "flag"


class TestAggregate:
    def test_majority_flag_escalates(self):
        runs = [{"verdict": "pass", "findings": []},
                {"verdict": "flag", "findings": ["a"]},
                {"verdict": "flag", "findings": ["b"]}]
        r = aggregate(runs)
        assert r["verdict"] == "flag"        # 2 escalating >= min_to_block(2)
        assert r["escalating"] == 2
        assert r["stable"] is False

    def test_minority_flag_passes(self):
        runs = [{"verdict": "pass", "findings": []},
                {"verdict": "pass", "findings": []},
                {"verdict": "flag", "findings": ["x"]}]
        r = aggregate(runs)
        assert r["verdict"] == "pass"        # 1 < 2
        assert r["findings"] == []           # no findings emitted on a pass

    def test_all_pass_stable(self):
        runs = [{"verdict": "pass", "findings": []} for _ in range(3)]
        r = aggregate(runs)
        assert r["verdict"] == "pass"
        assert r["stable"] is True

    def test_error_counts_as_escalating(self):
        runs = [{"verdict": "error", "findings": ["boom"]},
                {"verdict": "error", "findings": ["boom"]},
                {"verdict": "pass", "findings": []}]
        r = aggregate(runs)
        assert r["verdict"] == "flag"        # error escalates like flag
        assert "boom" in r["findings"]

    def test_findings_capped_at_five(self):
        runs = [{"verdict": "flag", "findings": [f"f{i}" for i in range(8)]},
                {"verdict": "flag", "findings": ["g"]}]
        r = aggregate(runs)
        assert len(r["findings"]) <= 5


class TestRenderPr:
    def test_flag_headline_needs_review(self):
        out = _render_pr({"verdict": "flag", "files": ["package.json"],
                          "findings": ["major"], "runs": ["flag", "flag"]})
        assert "needs human review" in out
        assert "FLAG" in out
        assert "package.json" in out

    def test_pass_headline_routine(self):
        out = _render_pr({"verdict": "pass", "files": ["go.mod"],
                          "findings": [], "runs": ["pass", "pass"]})
        assert "routine bump" in out
        assert "PASS" in out

    def test_includes_validator_marker(self):
        out = _render_pr({"verdict": "pass", "files": [], "findings": [], "runs": []})
        assert "review-hub:dependency-update" in out


class TestBuildPrompt:
    def test_substitutes_input(self):
        out = build_prompt([("package.json", "@@ diff-body @@")], "bumped foo 1->2")
        assert "{{INPUT}}" not in out        # template placeholder was replaced
        assert "package.json" in out
        assert "diff-body" in out
        assert "bumped foo 1->2" in out

    def test_no_changelog_section_when_absent(self):
        out = build_prompt([("go.mod", "x")], "")
        assert "CHANGELOG" not in out
