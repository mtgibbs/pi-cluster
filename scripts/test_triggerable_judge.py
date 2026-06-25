import pytest
from triggerable_judge import (
    parse_verdict,
    aggregate_runs,
    CRITERIA,
    BEGIN,
    END,
    TRIGGERABLE_LABEL,
)


class TestParseVerdict:
    """Tests for parse_verdict() - JSON extraction between markers."""

    def test_basic_pass(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\", \"criteria\": [\"idempotent\"], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result == {
            "verdict": "pass",
            "criteria": ["idempotent"],
            "findings": [],
            "ok": True
        }

    def test_basic_fail(self):
        text = f"{BEGIN}\n{{\"verdict\": \"fail\", \"criteria\": [\"idempotent\", \"quota-safe\"], \"findings\": [\"no idempotency\"]}}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "fail"
        assert set(result["criteria"]) == {"idempotent", "quota-safe"}
        assert result["findings"] == ["no idempotency"]
        assert result["ok"] is True

    def test_basic_flag(self):
        text = f"{BEGIN}\n{{\"verdict\": \"flag\", \"criteria\": [\"fails-safe\"], \"findings\": [\"may fail silently\"]}}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "flag"
        assert result["ok"] is True

    def test_missing_begin_marker(self):
        text = "No markers here, just prose."
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False
        assert "no verdict markers" in result["findings"][0]

    def test_missing_end_marker(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\"}}\nSome text after without end marker"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False

    def test_extra_prose_before_begin(self):
        text = """Here's some analysis.

===VERDICT-BEGIN===
{"verdict": "pass", "criteria": ["idempotent"], "findings": []}
===VERDICT-END===
Some trailing prose."""
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["verdict"] == "pass"

    def test_extra_prose_after_end(self):
        text = f"""Analysis text...

{BEGIN}
{{
  "verdict": "fail",
  "criteria": ["quota-safe"],
  "findings": ["hit quota"]
}}
{END}

Some final remarks."""
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["verdict"] == "fail"

    def test_multiple_begin_end_pairs_last_wins(self):
        text = f"""First pair:
{BEGIN}
{{"verdict": "pass", "criteria": [], "findings": []}}
{END}

Second pair (should win):
{BEGIN}
{{"verdict": "fail", "criteria": ["time-insensitive"], "findings": ["uses time"]}}
{END}"""
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["verdict"] == "fail"
        assert "time-insensitive" in result["criteria"]

    def test_empty_body_between_markers(self):
        text = f"{BEGIN}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False
        assert "unparseable JSON" in result["findings"][0]

    def test_whitespace_only_body(self):
        text = f"{BEGIN}\n   \n\t\n  {END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False

    def test_invalid_json_syntax(self):
        text = f"{BEGIN}\n{{invalid json here\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False
        assert "unparseable JSON" in result["findings"][0]

    def test_bad_verdict_value(self):
        text = f"{BEGIN}\n{{\"verdict\": \"maybe\", \"criteria\": [], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False
        assert "bad verdict" in result["findings"][0]

    def test_invalid_verdict_null(self):
        text = f"{BEGIN}\n{{\"verdict\": null, \"criteria\": [], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False

    def test_invalid_verdict_missing(self):
        text = f"{BEGIN}\n{{\"criteria\": [], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["verdict"] == "error"
        assert result["ok"] is False

    def test_criteria_with_unknown_values_filtered(self):
        text = f"{BEGIN}\n{{\"verdict\": \"fail\", \"criteria\": [\"idempotent\", \"unknown-criterion\", \"concurrency-tolerant\"], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["ok"] is True
        assert "idempotent" in result["criteria"]
        assert "concurrency-tolerant" in result["criteria"]
        assert "unknown-criterion" not in result["criteria"]

    def test_empty_criteria_list(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\", \"criteria\": [], \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["criteria"] == []

    def test_missing_criteria_key(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\", \"findings\": []}}\n{END}"
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["criteria"] == []

    def test_missing_findings_key(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\", \"criteria\": [\"idempotent\"]}}\n{END}"
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["findings"] == []

    def test_null_findings(self):
        text = f"{BEGIN}\n{{\"verdict\": \"pass\", \"criteria\": [], \"findings\": null}}\n{END}"
        result = parse_verdict(text)
        assert result["ok"] is True
        assert result["findings"] == []


class TestAggregateRuns:
    """Tests for aggregate_runs() - collapsing multiple runs into one verdict."""

    def test_clear_majority_pass(self):
        results = [
            {"verdict": "pass", "criteria": [], "findings": []},
            {"verdict": "pass", "criteria": [], "findings": []},
            {"verdict": "pass", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "pass"
        assert agg["stable"] is True
        assert agg["runs"] == ["pass", "pass", "pass"]

    def test_majority_pass_with_one_flag(self):
        results = [
            {"verdict": "pass", "criteria": [], "findings": []},
            {"verdict": "flag", "criteria": ["fails-safe"], "findings": ["may fail silently"]},
            {"verdict": "pass", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "flag"
        assert agg["stable"] is False
        assert "fails-safe" in agg["criteria"]

    def test_all_fail(self):
        results = [
            {"verdict": "fail", "criteria": ["idempotent"], "findings": ["not idempotent"]},
            {"verdict": "fail", "criteria": ["quota-safe"], "findings": ["quota exceeded"]},
            {"verdict": "fail", "criteria": ["fails-safe"], "findings": ["no fallback"]}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "fail"
        assert set(agg["criteria"]) == {"idempotent", "quota-safe", "fails-safe"}
        assert agg["stable"] is True

    def test_fail_overrides_flag(self):
        results = [
            {"verdict": "flag", "criteria": [], "findings": []},
            {"verdict": "fail", "criteria": ["idempotent"], "findings": ["bad"]}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "fail"
        assert "idempotent" in agg["criteria"]

    def test_fail_wins_over_error_and_pass(self):
        results = [
            {"verdict": "pass", "criteria": [], "findings": []},
            {"verdict": "error", "criteria": [], "findings": ["timeout"]},
            {"verdict": "fail", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "fail"
        assert "error" in agg["runs"]
        assert agg["stable"] is False

    def test_single_run(self):
        results = [
            {"verdict": "fail", "criteria": ["concurrency-tolerant"], "findings": ["race condition"]}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "fail"
        assert "concurrency-tolerant" in agg["criteria"]
        assert agg["stable"] is True
        assert agg["runs"] == ["fail"]

    def test_tie_between_fail_and_pass(self):
        results = [
            {"verdict": "fail", "criteria": [], "findings": []},
            {"verdict": "pass", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "fail"
        assert agg["stable"] is False

    def test_tie_between_flag_and_pass(self):
        results = [
            {"verdict": "flag", "criteria": [], "findings": []},
            {"verdict": "pass", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "flag"
        assert agg["stable"] is False

    def test_criteria_aggregation_from_multiple_runs(self):
        results = [
            {"verdict": "fail", "criteria": ["idempotent"], "findings": ["dup"]},
            {"verdict": "flag", "criteria": ["quota-safe"], "findings": ["quota"]},
            {"verdict": "fail", "criteria": ["fails-safe"], "findings": ["fallback"]}
        ]
        agg = aggregate_runs(results)
        assert set(agg["criteria"]) == {"idempotent", "quota-safe", "fails-safe"}
        assert agg["verdict"] == "fail"

    def test_findings_aggregation(self):
        results = [
            {"verdict": "fail", "criteria": [], "findings": ["first finding"]},
            {"verdict": "fail", "criteria": [], "findings": ["second finding"]},
            {"verdict": "pass", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert "first finding" in agg["findings"]
        assert "second finding" in agg["findings"]
        assert len(agg["findings"]) <= 6

    def test_findings_capped_at_six(self):
        results = []
        for i in range(10):
            results.append({"verdict": "fail", "criteria": [], "findings": [f"finding {i}"]})
        agg = aggregate_runs(results)
        assert len(agg["findings"]) <= 6

    def test_pass_with_criteria_does_not_appear_in_agg_criteria(self):
        results = [
            {"verdict": "pass", "criteria": ["idempotent"], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["verdict"] == "pass"
        assert agg["criteria"] == []

    def test_criteria_only_from_fail_flag(self):
        results = [
            {"verdict": "fail", "criteria": ["idempotent"], "findings": []},
            {"verdict": "flag", "criteria": ["quota-safe"], "findings": []},
            {"verdict": "pass", "criteria": ["time-insensitive"], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert set(agg["criteria"]) == {"idempotent", "quota-safe"}

    def test_runs_list_preserves_order(self):
        results = [
            {"verdict": "pass", "criteria": [], "findings": []},
            {"verdict": "flag", "criteria": [], "findings": []},
            {"verdict": "fail", "criteria": [], "findings": []}
        ]
        agg = aggregate_runs(results)
        assert agg["runs"] == ["pass", "flag", "fail"]


class FakeForge:
    """Minimal fake Forge for testing select_triggerable_targets."""
    
    def __init__(self, changed_files_list):
        self._files = changed_files_list
        self._content = {}
    
    def changed_files(self):
        return self._files
    
    def get_file(self, path, ref=None):
        return self._content.get(path)


def make_cronjob_doc(name, namespace="default", triggerable=False):
    doc = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"schedule": "* * * * *", "jobTemplate": {"spec": {"template": {"spec": {"containers": [{"name": "test", "image": "test"}], "restartPolicy": "OnFailure"}}}}}
    }
    if triggerable:
        doc["metadata"]["labels"] = {TRIGGERABLE_LABEL: "true"}
    return doc


class TestSelectTriggerableTargets:
    """Tests for select_triggerable_targets() with fake Forge."""

    def test_no_changed_files(self):
        forge = FakeForge([])
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert targets == []

    def test_non_yaml_files_ignored(self):
        forge = FakeForge(["file.txt", "config.json", "script.py"])
        forge._content = {
            "file.txt": "some text",
            "config.json": '{"key": "value"}',
            "script.py": "print('hello')"
        }
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert targets == []

    def test_yaml_without_triggerable_label(self):
        forge = FakeForge(["job.yaml"])
        forge._content = {
            "job.yaml": """
apiVersion: batch/v1
kind: CronJob
metadata:
  name: non-triggerable
  namespace: default
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test
            image: test
          restartPolicy: OnFailure
"""
        }
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert targets == []

    def test_yaml_with_triggerable_label(self):
        forge = FakeForge(["job.yaml"])
        forge._content = {
            "job.yaml": f"""
apiVersion: batch/v1
kind: CronJob
metadata:
  name: my-triggerable-job
  namespace: default
  labels:
    {TRIGGERABLE_LABEL}: "true"
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test
            image: test
          restartPolicy: OnFailure
"""
        }
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert len(targets) == 1
        path, doc = targets[0]
        assert path == "job.yaml"
        assert doc["metadata"]["name"] == "my-triggerable-job"

    def test_multiple_yaml_files_mixed(self):
        forge = FakeForge(["a.yaml", "b.yaml", "c.yml"])
        forge._content = {
            "a.yaml": f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: job-a
  labels:
    {TRIGGERABLE_LABEL}: "true"
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test
            image: test
          restartPolicy: OnFailure
""",
            "b.yaml": """apiVersion: batch/v1
kind: CronJob
metadata:
  name: job-b
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test
            image: test
          restartPolicy: OnFailure
""",
            "c.yml": f"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: job-c
  labels:
    {TRIGGERABLE_LABEL}: "true"
spec:
  schedule: "* * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: test
            image: test
          restartPolicy: OnFailure
"""
        }
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert len(targets) == 2
        paths = [p for p, _ in targets]
        assert "a.yaml" in paths
        assert "c.yml" in paths

    def test_missing_file_content(self):
        forge = FakeForge(["job.yaml"])
        forge._content = {}
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert targets == []

    def test_empty_yaml_content(self):
        forge = FakeForge(["empty.yaml"])
        forge._content = {"empty.yaml": ""}
        from triggerable_judge import select_triggerable_targets
        targets = select_triggerable_targets(forge)
        assert targets == []
