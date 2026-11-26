#!/usr/bin/env python3
"""loop-control.py <out-dir> [--intent-raise] — build a no-model positive control for the spec
vote + revise loops.

Copies mcp/workflow.fabro and swaps four nodes, leaving every capture/vote/raised/pass/none/
note/forward/lock node and every edge between them verbatim:
  * ideate      -> a command that writes a fixed spec and prints the feedback files it sees
  * spec_judge  -> a single-shot prompt told to reply `raise` with the packet's SPEC-ID
  * spec_intent -> a single-shot prompt told to reply `pass` with the INTENT-ID (default), or,
                   with --intent-raise, `raise` with one `added:` reason
  * conf_intent -> a single-shot prompt told to reply `pass` with the CHANGE-ID (never reached
                   unless someone approves the control's gate, which they must not)
The build half of the graph is left in place (Fabro rejects unreachable nodes): answer the
gate with a typed note or Reject, never Approve.
Upload it with submit.sh (FACTORY_WORKFLOW_DIR=<out-dir>) and read the stage list.

Single-vote control (any profile with spec_votes=1, e.g. all-local), --panel "spec_rounds=2":
a judge that always raises gives judge->capture->vote->raised, 2 automatic revise rounds,
then the human gate marked raise; a typed note sends it round once more.

Vote-loop control, --panel "spec_votes=3 spec_threshold=2 spec_rounds=2": every round casts
exactly TWO votes (the second raise decides it; the third is never cast), the vote stage
logs `round r, vote 1` / `vote 2` and `decided: rN raise (2 raise / 0 pass / 0 none of 2
cast; panel 3, threshold 2)`; 2 automatic revise rounds, ideate sees
"2 of 3 voters raised (2 votes cast ...)" with Voter 1 and Voter 2 sections; the third raise
goes to the gate. Answer [F]: spec_forward -> ideate, whose IDEATE-SEES-NOTE shows the
forwarded objections; the fourth raise goes straight back to the gate. Then Reject.
With the intent panels in front, every round above is preceded by
spec_intent -> spec_intent_capture -> spec_intent_vote (r<N>v1 pass) -> spec_intent_pass, whose
log names the SPEC-ID the rigor panel votes on next; the intent stand-in never raises.

Intent-raise control (--intent-raise), --panel "spec_intent_rounds=2": every round is
spec_check -> spec_intent -> spec_intent_capture -> spec_intent_vote (raise) -> spec_intent_raised;
spec_judge is NEVER visited. 2 automatic revise rounds (ideate's IDEATE-SEES-INTENT-FEEDBACK
shows "added: control objection: always raise" under "1 of 1 voters raised"), the third raise
goes to the gate (lock prints three spec intent rounds and "spec rigor panel: not run on this
version"). Answer [F]: spec_forward forwards the INTENT round (IDEATE-SEES-NOTE shows "Spec
intent panel objections forwarded"), the fourth intent raise goes straight back to the gate.
Then Reject.
"""
import pathlib, re, sys
here = pathlib.Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1 or set(sys.argv[1:]) - set(args) - {"--intent-raise"}:
    sys.exit("usage: loop-control.py <out-dir> [--intent-raise]")
intent_raise = "--intent-raise" in sys.argv
out = pathlib.Path(args[0]); (out / "prompts").mkdir(parents=True, exist_ok=True)
g = (here / "mcp" / "workflow.fabro").read_text()
fake_ideate = ('ideate [label="CONTROL ideate (fixed spec)", max_visits=24, script="d=specs/{{ inputs.spec }}; mkdir -p $d; '
               "echo '# Spec: control' > $d/spec.md; echo 'T1: x' > $d/tasks.txt; printf '#!/usr/bin/env bash\\\\nexit 1\\\\n' > $d/verify.sh; "
               "echo IDEATE-SEES-INTENT-FEEDBACK:; cat /tmp/factory/spec-intent-feedback.md 2>/dev/null; "
               "echo IDEATE-SEES-FEEDBACK:; cat /tmp/factory/spec-feedback.md 2>/dev/null; echo IDEATE-SEES-NOTE:; cat /tmp/factory/human-note.md 2>/dev/null; true\"]")


def stand_in(node, idtag, verdict, reason):
    """A single-shot judge that finds the LAST `<idtag>: <12 hex>` line above and replies `verdict`."""
    return (f'{node} [shape=tab, max_visits=60, prompt="Find the LAST line in the stage output above that contains the text {idtag}; '
            'the id is the 12 hex characters right after it. Reply with exactly one line and nothing else: '
            f'{{\\"factory_verdict\\": \\"{verdict}\\", \\"id\\": \\"<that id>\\", \\"reasons\\": [\\"{reason}\\"]}}"]')


fake_spec_intent = (stand_in("spec_intent", "INTENT-ID", "raise", "added: control objection: always raise") if intent_raise
                    else stand_in("spec_intent", "INTENT-ID", "pass", "control: always pass"))
fake_conf_intent = stand_in("conf_intent", "CHANGE-ID", "pass", "control: always pass")
fake_judge = stand_in("spec_judge", "SPEC-ID", "raise", "control objection: always raise")
g, n1 = re.subn(r'ideate \[label="Ideate.*?\]', lambda m: fake_ideate, g, count=1)
g, n2 = re.subn(r'spec_judge \[label="Spec rigor judge.*?\]', lambda m: fake_judge, g, count=1)
g, n3 = re.subn(r'spec_intent \[label="Spec intent.*?\]', lambda m: fake_spec_intent, g, count=1)
g, n4 = re.subn(r'conf_intent \[label="Change intent.*?\]', lambda m: fake_conf_intent, g, count=1)
assert n1 == n2 == n3 == n4 == 1, (n1, n2, n3, n4)
(out / "workflow.fabro").write_text(g)
(out / "workflow.toml").write_text((here / "mcp" / "workflow.toml").read_text())
for p in (here / "mcp" / "prompts").iterdir():
    (out / "prompts" / p.name).write_text(p.read_text())
print("wrote", out, "(spec intent stand-in: " + ("always RAISE" if intent_raise else "always pass") + ")")
