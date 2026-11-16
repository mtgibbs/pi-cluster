"""Plan discipline (CONTRACT §5b, runtime 0.3.0): every finding is a plan, rules come from a closed vocabulary,
resources are canonical, evidence is cited — one corrective re-prompt, then a deterministic settlement.
The regressions are the sec-researcher runs of 2026-11-13 (findings with no plans; a rollout filed as a
finding under an unrelated rule; an inference-only plan)."""
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import result as R  # noqa: E402
from test_agent_run import FakeLLM, FakeMCP, TOOLS, run_agent, servers, submit, tool_messages  # noqa: E402,F401
from test_repo_checkout import (SEC_EVENT, checkout_env, plan, repo, runner_accepts,  # noqa: E402,F401
                                sec_manifest)

ROOT = HERE.parents[1]
MANIFEST = ROOT / "clusters/pi-k3s/agents/manifests/sec-researcher.yaml"
PLAN_ITEMS_JS = ROOT / "clusters/pi-k3s/n8n/workflows/src/agent-sec-plan-items.js"
# Rules issues in mtgibbs/homelab-plans were filed under (their fingerprints must stay reproducible).
FILED = {"secret-shared-across-roles": "agents/ExternalSecret/agent-sec-researcher",   # issue 1
         "rbac-escalation-verbs": "agents/Role/agent-runner"}                         # issue 2
ISSUE1_FP_PREFIX = "8e54af265623b53a"


def info_plan(**over):
    return plan(severity="info", title="Shared read-only homelab-MCP key",
                fingerprint={"rule": "secret-shared-across-roles",
                             "resource": "agents/ExternalSecret/agent-sec-researcher"}, **over)


def run_sec(servers, repo, replies):
    mcp = servers(FakeMCP, TOOLS)
    llm = servers(FakeLLM, replies)
    res, logs, _ = run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, extra_env=checkout_env(repo))
    assert runner_accepts(res) == (True, None)
    return res, logs, llm


# -- the vocabulary is one list in four places ----------------------------------------------------
def test_vocabulary_matches_prompt_and_n8n():
    vocab = set(R.PLAN_RULES)
    prompt = MANIFEST.read_text().split("\nprompt: |\n", 1)[1]   # no PyYAML in this image's CI
    in_prompt = set(re.findall(r"\b(?:rbac|sa|netpol|pod|psa|image|secret|ingress|service)-[a-z][a-z-]*[a-z]\b",
                               prompt))
    assert in_prompt == vocab, (sorted(in_prompt - vocab), sorted(vocab - in_prompt))
    js = PLAN_ITEMS_JS.read_text()
    block = re.search(r"const RULES = new Set\(\[(.*?)\]\);", js, re.S).group(1)
    assert set(re.findall(r"'([a-z0-9-]+)'", block)) == vocab
    assert all(R.PLAN_RULE_RE.match(r) for r in vocab)
    for kinds in (k for _, k in R.PLAN_RULES.values() if k):
        assert all(k in R.CLUSTER_SCOPED_KINDS + R.NAMESPACED_KINDS for k in kinds)


def test_filed_fingerprints_stay_valid():
    """Every rule an issue was filed under stays in the vocabulary, and issue 1's pair is still acceptable
    as written, so a re-report updates that issue instead of opening a duplicate."""
    assert {"secret-shared-across-roles", "rbac-escalation-verbs", "psa-not-enforced"} <= set(R.PLAN_RULES)
    for rule, resource in FILED.items():
        p = plan(fingerprint={"rule": rule, "resource": resource})
        assert R.plan_problems(p) == [] and R.plan_semantic_problems(p) == [], rule
    fp = hashlib.sha256(b"sec-researcher|secret-shared-across-roles|agents/ExternalSecret/agent-sec-researcher")
    assert fp.hexdigest().startswith(ISSUE1_FP_PREFIX)


def test_schema_offers_the_closed_vocabulary(servers, repo):
    _, _, llm = run_sec(servers, repo, [submit(outcome="nothing_to_do", summary="checked rbac.yaml", outputs=[])])
    sub = next(t for t in llm.requests[0]["json"]["tools"] if t["function"]["name"] == "submit_result")
    rule = sub["function"]["parameters"]["properties"]["outputs"]["items"]["properties"]["fingerprint"][
        "properties"]["rule"]
    assert rule["enum"] == list(R.PLAN_RULES) and "psa-not-enforced = " in rule["description"]


# -- per-plan checks ------------------------------------------------------------------------------
def test_semantic_problems():
    ok = plan()
    assert R.plan_semantic_problems(ok) == []
    cases = {
        "made-up-rule": plan(fingerprint={"rule": "made-up-rule", "resource": "agents/Role/agent-runner"}),
        "spelled 'NetworkPolicy'": plan(fingerprint={"rule": "netpol-broad-egress",
                                                     "resource": "agents/Networkpolicy/agent-base-egress"}),
        "cluster-scoped": plan(fingerprint={"rule": "rbac-wildcard", "resource": "agents/ClusterRole/foo"}),
        "is namespaced": plan(fingerprint={"rule": "pod-privileged", "resource": "cluster/Deployment/x"}),
        # 2026-11-13 run ae3282098d234088: a rollout filed under psa-not-enforced on a Deployment
        "applies to Namespace": plan(fingerprint={"rule": "psa-not-enforced",
                                                  "resource": "agents/Deployment/agent-runner"}),
        "must cite": plan(plan={**plan()["plan"], "evidence": "the Role probably allows more than it should"}),
        # 2026-11-13: "... (info, inference)"
        "inference": plan(title="Role can create Jobs; no check that Jobs cannot reference Secrets (inference)"),
    }
    for want, p in cases.items():
        probs = R.plan_semantic_problems(p, ["get_flux_status"])
        assert any(want in x for x in probs), (want, probs)
    # a live tool result is evidence too (bare or prefixed name)
    for ev in ("homelab__describe_resource: securityContext.privileged=true",
               "describe_resource agents/agent-runner -> runAsNonRoot: unset"):
        p = plan(plan={**plan()["plan"], "evidence": ev})
        assert R.plan_semantic_problems(p, ["describe_resource", "homelab__describe_resource"]) == []
    for ev in ("clusters/pi-k3s/agents/rbac.yaml:12-15", "clusters/pi-k3s/agents/rbac.yaml lines 12-15",
               "rbac.yaml#L12", "docs/secrets-map.md (line 40)"):
        assert R.plan_semantic_problems(plan(plan={**plan()["plan"], "evidence": ev})) == [], ev
    assert R.plan_semantic_problems(plan(plan={**plan()["plan"], "evidence": "clusters/pi-k3s/agents/rbac.yaml"}))


def test_summary_claims():
    assert R.summary_claims("Findings: 1 low (agent container root filesystem writable) and 1 info "
                            "(shared read-only MCP key)") == ({"low": 1, "info": 1}, 0)
    assert R.summary_claims("Two findings: one high, one informational.") == ({"high": 1, "info": 1}, 2)
    assert R.summary_claims("No findings; 0 high, 0 critical. Checked 4 namespaces for issues.") == ({}, 0)
    assert R.summary_claims("Reviewed 12 files in agents/.") == ({}, 0)


# -- the loop: one re-prompt, then settle ---------------------------------------------------------
def test_findings_without_plans_reprompted_then_plans_returned(servers, repo):
    """Run f2cc2cb474a441ba: needs_human, 'Findings: 1 low ... 1 info', zero plans."""
    lost = "Reviewed agents/. Findings: 1 low (agent root filesystem writable) and 1 info (shared MCP key)."
    low = plan(severity="low", title="agent-runner root filesystem writable",
               fingerprint={"rule": "pod-writable-rootfs", "resource": "agents/Deployment/agent-runner"})
    res, logs, llm = run_sec(servers, repo, [submit(outcome="needs_human", summary=lost, outputs=[]),
                                             submit(outcome="needs_human", summary=lost, outputs=[low, info_plan()])])
    err = tool_messages(llm.requests[1])[-1]["content"]
    assert "every finding must be a plan" in err and "only correction" in err
    assert res["outcome"] == "needs_human" and len(res["outputs"]) == 2 and "agent-runtime" not in res["summary"]
    assert sum(1 for r in logs if r["event"] == "submit_reviewed") == 1


def test_findings_without_plans_twice_is_flagged_not_lost(servers, repo):
    lost = "Findings: 1 low and 1 info."
    res, logs, llm = run_sec(servers, repo, [submit(outcome="needs_human", summary=lost, outputs=[]),
                                             submit(outcome="nothing_to_do", summary=lost, outputs=[])])
    assert len(llm.requests) == 2                       # exactly one corrective re-prompt
    assert res["outcome"] == "needs_human" and res["outputs"] == []
    assert "not among the 0 plan(s)" in res["summary"]


def test_bad_plan_after_the_one_reprompt_is_dropped(servers, repo):
    drift = plan(severity="info", title="Live agent-runner runs 0.3.0 while Git pins 0.4.0",
                 fingerprint={"rule": "psa-not-enforced", "resource": "agents/Deployment/agent-runner"},
                 plan={**plan()["plan"], "evidence": "get_flux_status: agents Kustomization not ready"})
    res, logs, llm = run_sec(servers, repo, [
        submit(outcome="done", summary="1 info, 1 high", outputs=[drift, plan()]),
        submit(outcome="done", summary="1 info, 1 high", outputs=[drift, plan()])])
    assert len(llm.requests) == 2
    assert "applies to Namespace" in tool_messages(llm.requests[1])[-1]["content"]
    assert res["outputs"] == [plan()]                    # the high plan survives; the drift item is not filed
    assert res["outcome"] == "needs_human"               # derived from the remaining plan, not the model's `done`
    assert "dropped 1 plan(s)" in res["summary"] and "psa-not-enforced agents/Deployment/agent-runner" in res["summary"]
    assert "not among" in res["summary"]                 # the summary still counted the dropped one
    final = [r for r in logs if r["event"] == "submit_result"][-1]
    assert final["dropped"] == 1 and final["submitted_outcome"] == "done"


def test_outcome_is_derived_from_plans_without_a_reprompt(servers, repo):
    res, logs, llm = run_sec(servers, repo, [submit(outcome="needs_human", summary="1 info", outputs=[info_plan()])])
    assert len(llm.requests) == 1 and res["outcome"] == "done" and res["outputs"] == [info_plan()]
    res, _, _ = run_sec(servers, repo, [submit(outcome="done", summary="Reviewed agents.", outputs=[])])
    assert res["outcome"] == "nothing_to_do"


def test_open_question_is_not_a_finding(servers, repo):
    q = "Reviewed agents/. No findings. Open question: should rendered Jobs be barred from other Secrets?"
    res, _, llm = run_sec(servers, repo, [submit(outcome="nothing_to_do", summary=q, outputs=[])])
    assert len(llm.requests) == 1 and res == {"outcome": "nothing_to_do", "summary": q, "outputs": []}
    res, _, llm = run_sec(servers, repo, [submit(outcome="needs_human", summary=q, outputs=[])])
    assert len(llm.requests) == 1 and res["outcome"] == "needs_human"      # a stated question for Matt
    res, _, llm = run_sec(servers, repo, [submit(outcome="needs_human", summary="Reviewed agents.", outputs=[]),
                                          submit(outcome="needs_human", summary="Reviewed agents.", outputs=[])])
    assert "stated question" in tool_messages(llm.requests[1])[-1]["content"]
    assert res["outcome"] == "nothing_to_do"


def test_failed_is_left_alone(servers, repo):
    res, _, llm = run_sec(servers, repo, [submit(outcome="failed", summary="tools down; 1 high suspected",
                                                 outputs=[])])
    assert len(llm.requests) == 1 and res["outcome"] == "failed"


def test_non_plan_agents_are_untouched():
    args = {"outcome": "needs_human", "summary": "1 high finding", "outputs": [
        {"kind": "report", "title": "t", "body": "b"}]}
    assert R.review_submission(args, ["report"]) == []
    assert R.enforce_discipline(args, ["report"]) == (args, [])
