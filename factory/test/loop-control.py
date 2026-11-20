#!/usr/bin/env python3
"""loop-control.py <out-dir> — build a no-model positive control for the spec revise loop.

Copies mcp/workflow.fabro and swaps exactly two things, leaving every capture/raised/
note/lock node and every edge between them verbatim:
  * ideate      -> a command that writes a fixed spec and prints the feedback files it sees
  * spec_judge  -> a single-shot prompt told to reply `raise` with the packet's SPEC-ID
The build half of the graph is left in place (Fabro rejects unreachable nodes): answer the
gate with a typed note or Reject, never Approve.
A judge that always raises must produce: 2 automatic revise rounds, then the human gate
marked raise; a typed note must send it round once more. Upload the out-dir with
submit-style inputs (see README "Running it") and read the stage list.
"""
import pathlib, re, sys
here = pathlib.Path(__file__).resolve().parent.parent
out = pathlib.Path(sys.argv[1]); (out / "prompts").mkdir(parents=True, exist_ok=True)
g = (here / "mcp" / "workflow.fabro").read_text()
fake_ideate = ('ideate [label="CONTROL ideate (fixed spec)", max_visits=8, script="d=specs/{{ inputs.spec }}; mkdir -p $d; '
               "echo '# Spec: control' > $d/spec.md; echo 'T1: x' > $d/tasks.txt; printf '#!/usr/bin/env bash\\\\nexit 1\\\\n' > $d/verify.sh; "
               "echo IDEATE-SEES-FEEDBACK:; cat /tmp/factory/spec-feedback.md 2>/dev/null; echo IDEATE-SEES-NOTE:; cat /tmp/factory/human-note.md 2>/dev/null; true\"]")
fake_judge = ('spec_judge [shape=tab, max_visits=8, prompt="Find a line containing SPEC-ID in the stage output above; the id is the 12 hex characters after it. '
              'Reply with exactly one line and nothing else: {\\"factory_verdict\\": \\"raise\\", \\"id\\": \\"<that id>\\", \\"reasons\\": [\\"control objection: always raise\\"]}"]')
g, n1 = re.subn(r'ideate \[label="Ideate.*?\]', lambda m: fake_ideate, g, count=1)
g, n2 = re.subn(r'spec_judge \[label="Spec judge".*?\]', lambda m: fake_judge, g, count=1)
assert n1 == n2 == 1
(out / "workflow.fabro").write_text(g)
(out / "workflow.toml").write_text((here / "mcp" / "workflow.toml").read_text())
for p in (here / "mcp" / "prompts").iterdir():
    (out / "prompts" / p.name).write_text(p.read_text())
print("wrote", out)
