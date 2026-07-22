# Spec: pulse — messages arc, and leave threads that braid into rope

## 1. Why · [R]

Transmissions currently travel a straight line and vanish on arrival in 1.15s. Two problems,
and they are really the same problem:

1. **You have to be looking at the exact second.** A ralph loop narrates 3–5 times across ten
   minutes. Each render lasts about one second. Watched live during a real run, the board looked
   inert — everything was working and nothing was visible.
2. **Nothing accumulates.** The board shows the instant and forgets it, so it can answer "is
   something happening right now" but never "who has been working with whom." The interesting
   fact about a house of agents is the *pattern of traffic*, and a straight line that disappears
   cannot carry it.

So: give a message a flight path worth watching, and let its path persist as a fading thread.
Threads between the same pair overlap into a visible rope, and the rope's thickness *is* the
history of that pair's chatter. No new data required — this is the same events, drawn honestly
over a longer window.

## 2. Outcomes (Definition of Done) · [R]

- A message visibly **arcs** out and back rather than sliding along the chord.
- After it lands, its path **remains as a thread** that fades over tens of seconds.
- Repeated traffic between the same two agents **reads as a thickening rope**, not one line
  redrawn.
- A quiet house fades back to bare atoms — the rope is not permanent.
- Nothing accumulates without bound, and reduced-motion users are not spun around.

## 3. Entities · [E]

| Entity | Meaning |
|---|---|
| `strand` | one message's flight path: `{from, to, born, seed}` — outlives the packet |
| `strands` | all live strands, newest last, capped |
| `packet` | the bright travelling head; exists only while `age < TRAVEL_MS` |
| `rope` | **not an object.** The visual result of several strands overlapping. |

## 4. Approach · [A]

**The rope is emergent, not modelled.** Do not aggregate per-pair weights. Draw each strand as
its own fading arc; where several exist between the same two atoms they superimpose — the canvas
already composites with `lighter`, so more chatter is literally more light in the same place.
That keeps thickness *truthful*: it can only reflect messages that actually happened.

Give each strand a small deterministic jitter in its arc bulge (from its `seed`), so a busy pair
reads as a **braid of threads** rather than one thick stroke redrawn N times. That is what makes
it look like rope instead of a highlighter.

**Anchor arcs to live atom positions, not to remembered coordinates.** The atoms drift under the
physics in `physics()`. A strand stored in world space would detach and float; recomputed from
`from.x/y` and `to.x/y` each frame, the rope stays tied to the minds it belongs to.

## 5. Scope · [S]

### In scope
- `harness-console/index.html` — all of it lives here.

### Out of scope
- The collector, the event contract, `/api/events`. **No new data is needed**; this is a
  rendering change over events that already arrive.
- `stepSimTrans()` behaviour (what it emits) — it keeps feeding the same `emit()`.
- The heartbeat/state path and the `feedState` work in `specs/pulse-live-feed`.

## 6. Prior decisions / facts the implementer must know · [S]

Read the file first; these are real and current.

- `emit(fromId, toIds)` creates transmissions; `stepTrans(dt)` ages them; `drawTrans()` renders.
  Constant today: `TRANS_DUR = 1.15`.
- `trans` entries are `{from, to, t}` where `from`/`to` are **live mind objects** (not ids), and
  `t` runs 0→1. `to` is `null` for a broadcast.
- On arrival `stepTrans` bumps `p.to.gust` — that reaction is deliberate and must survive.
- Rendering happens inside `frame()` under `ctx.globalCompositeOperation = "lighter"`, with
  `drawTrans()` called *before* the atom dust so a packet arrives **into** an atom.
- `minds[]` entries carry live `x`, `y`, `R`; the atoms are constantly moved by `physics(dt)`.
- A `reduce` flag already exists (prefers-reduced-motion) and scales `speed`.
- The page runs standalone with simulated traffic when there is no feed. Both paths use `emit()`,
  so both get this behaviour for free — do not special-case the sim.
- `specs/pulse-live-feed` also edits this file. **Whichever lands second rebases**; keep the
  diff confined to the transmission code so the two do not fight.

## 7. Norms · [N]

- Vanilla JS in the existing inline `<script>`. No libraries, no build step.
- Match the file's comment voice: say *why*, name the real thing that motivated it.
- Geometry helpers must be **pure functions of their arguments** — no reads of canvas state, no
  globals. The gate executes them (§11); an impure helper cannot be tested.
- Keep the existing names (`emit`, `stepTrans`, `drawTrans`) so the rest of the file and the sim
  keep working.

## 8. Safeguards · [S]

1. **Bounded.** `strands` never exceeds `STRAND_MAX`; oldest are dropped first.
2. **It must decay to nothing.** With no traffic for `STRAND_FADE_MS`, no strand is drawn. The
   board must be able to look quiet, or "busy" stops meaning anything.
3. **Broadcasts leave no thread.** A message addressed to nobody has no pair, so it cannot form
   rope — it keeps the expanding ring and nothing else.
4. **Per-frame cost stays flat in message count**, not quadratic: no pair-vs-pair scanning.
5. **Reduced motion is respected**: no orbital travel; the strand appears and fades.

## 9. Task breakdown · [O]

See `tasks.txt` — five tasks, all in `harness-console/index.html`.

## 10. Acceptance criteria (EARS) · [O]

1. **Where** a directed message is emitted, the page **shall** create exactly one strand
   recording `from`, `to`, birth time and a seed.
2. **While** a strand's age is below `TRAVEL_MS`, the page **shall** draw a travelling head along
   an arc; **where** age exceeds it, the head **shall not** be drawn.
3. **Where** `t` is 0 the arc **shall** return the sender's position and **where** `t` is 1 it
   **shall** return the receiver's; at `t = 0.5` the point **shall** be off the straight chord by
   at least 6% of the chord length (it is an arc, not a line).
4. **While** a strand's age is below `STRAND_FADE_MS`, its arc **shall** be drawn with opacity
   decreasing monotonically with age, reaching zero at `STRAND_FADE_MS`.
5. **Where** `STRAND_FADE_MS` is configured, it **shall** be between 30000 and 60000 ms.
6. **Where** several strands share the same pair, each **shall** be drawn with its own seeded
   bulge offset so they read as separate threads.
7. **While** `strands.length` exceeds `STRAND_MAX`, the page **shall** discard oldest first.
8. **Where** a message has no target, the page **shall** create no strand.
9. **Where** reduced motion is preferred, the page **shall not** animate a travelling head.

## 11. Verification (the harness)

`./specs/pulse-threads/verify.sh` — STATIC, offline, presence-gated.

**AC3 is checked by executing the arc helper, not by grepping for it.** That is deliberate:
"it is an arc, not a straight line" is a claim about behaviour, and the last spec farmed out here
shipped a defect precisely because a behavioural criterion was compiled into a shape-grep
(see `specs/harness-multi-repo/verify.sh` and pi-cluster#86). The helper is required to be pure
so this is possible.

LIVE tier — human, after deploy: watch a real `harness run`; confirm arcs are visible, threads
persist for tens of seconds, repeated traffic braids, and the board returns to bare atoms when
the run ends.

## 12. Open questions

- Should a thread carry the *colour* of its sender, so a rope between two agents is visibly
  two-toned by who talks more? Attractive, and cheap. Deferred — decide once real traffic is
  visible, rather than guessing at it now.
