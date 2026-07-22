# Spec: pulse — the live feed never needs a refresh

## 1. Why · [R]

The pulse page (`pulse.lab.mtgibbs.dev`) is a wall dashboard. It is opened once and left open
for days. Today it can stop showing reality without saying so, and the only cure is a manual
refresh — which nobody is standing there to do.

Two distinct problems, and the second is the dangerous one:

1. **A wedged stream never recovers.** `EventSource` reconnects on a *transport error*. It does
   not reconnect when the connection stays open and simply stops delivering — the half-open TCP
   case after a laptop sleeps, a Wi-Fi roam, or a NAT rebind. No `onerror` fires, so the page
   waits forever on a socket that will never speak again.

2. **The fallback is indistinguishable from the real thing.** On any failure the page silently
   switches to `stepSimTrans()` — invented traffic between the same atoms with the same visual
   language. A convincing simulation of a healthy house is the *worst* possible failure display
   for a monitoring surface: the viewer is not merely uninformed, they are misinformed, and they
   have no way to notice.

A dashboard that lies confidently is worse than one that is blank.

## 2. Outcomes (Definition of Done) · [R]

- A page left open across sleep/wake and a network change is showing live data again **without
  human interaction**, within seconds of connectivity returning.
- A viewer glancing at the screen can always tell **LIVE vs SIMULATED** without reading code,
  clicking, or opening devtools.
- A burst of messages arriving at once renders as a **legible sequence**, not a simultaneous flash.
- No reconnect storm: a collector that is genuinely down is retried politely, forever.

## 3. Entities · [E]

| Entity | Meaning |
|---|---|
| `feedState` | exactly one of `live`, `stale`, `sim` — the single source of truth for what the page claims |
| `lastStateOk` | epoch ms of the last successful `/api/state` fetch |
| `lastStreamMsg` | epoch ms of the last SSE frame that reached `onmessage` |
| `txQueue` | events accepted but not yet animated (paced release) |
| `pollFails` | consecutive `/api/state` failures, for hysteresis |
| `feedNext` | **pure** decision function — see the worked example in §6 |
| `txAdmit` | **pure** queue admission — see §6 |

## 4. Approach · [A]

**Two independent liveness signals, and neither is trusted alone.**

The page already polls `/api/state` every 1.5s *and* holds an SSE stream. Treat them as
cross-checks rather than two unrelated features:

- `/api/state` succeeding proves **the collector is reachable**. It is a heartbeat we already pay
  for.
- The SSE stream is proven live only by frames that actually reach `onmessage`.

The key inference: **poll healthy + stream silent for too long = the stream is wedged, not the
house being quiet.** That is the exact condition `EventSource` cannot detect on its own, and
detecting it needs no cooperation from the server — which matters, because the collector lives
in a different repository (see §5).

When that condition holds, close the `EventSource` and open a new one. A fresh connection is
cheap; a wedged one is invisible.

## 5. Scope · [S]

### In scope
- `harness-console/index.html` — the entire change lives in this one file.

### Out of scope
- `files/harness-console/server.js` — **a different repository** (`beelink-ansible`). The qwen
  harness workspace only clones `pi-cluster`, so an executor here cannot touch it. Every
  behaviour below must therefore work against the collector exactly as it is today.
- Caddy, Synapse, the collector's Matrix `/sync` loop.
- Any new runtime dependency. There is no build step and no `npm install`.

## 6. Prior decisions / facts the implementer must know · [S]

Look these up before writing; they are all real and current:

- The file is `harness-console/index.html`, plain HTML + one inline `<script>`, no bundler.
- State polling is `poll()` on `setInterval(poll, 1500)`, hitting `/api/state`.
- `liveMode` (bool) currently flips to `false` on a **single** failed fetch, and toggles the
  `live` class on `document.body` and `controlsEl`.
- `busMode` (bool) is set by `es.onopen` / cleared by `es.onerror`.
- Transmissions are created by `emit(fromId, toIds)` and consumed by `stepTrans`/`drawTrans`.
- `stepSimTrans(dt)` invents traffic and is gated on `if (busMode) return;`.
- **The collector's keepalive is invisible to JavaScript.** It writes SSE *comment* frames
  (`: ka\n\n`) every 20s. Comments keep proxies from buffering but fire **no** `onmessage`
  event. Do not attempt to use them as a client-side heartbeat — they cannot be observed.
- The collector already sends `retry: 3000`, so `EventSource`'s own reconnect delay is 3s.
- The collector replays a ring buffer of up to 60 recent events on connect. The page drops any
  event older than 30s (`if (d.ts && (Date.now()/1000 - d.ts) > 30) return;`) so a reload does
  not fire a burst of history. **A reconnect re-delivers that backfill — the guard must keep
  working after every recycle, or each recycle causes a stale flash.**
- Opened standalone (e.g. `file://`, or the artifact preview) both endpoints fail. That path
  must keep working and must present as simulated.

### WORKED EXAMPLE — the decision is a pure function, copy this shape

Every criterion below is about *behaviour under a sequence of observations*, which a grep cannot
check. Three specs in this repo have now shipped or nearly shipped defects because a behavioural
criterion was compiled into a check on what the code looked like. So the decision is isolated
into a pure function the gate can lift out and run against a truth table.

```js
// Pure. Given the current state and what we just observed, decide the next state and whether
// the event stream needs recycling. Reads no globals, touches no DOM, no timers.
//   state            'live' | 'sim'
//   pollOk           did the most recent /api/state fetch succeed
//   pollFails        consecutive failures INCLUDING this one (0 when pollOk)
//   msSinceStream    ms since the last SSE frame reached onmessage
function feedNext(state, pollOk, pollFails, msSinceStream) {
  const next = pollOk ? "live" : (pollFails >= 3 ? "sim" : state);
  // Only a healthy poll makes stream silence meaningful: it separates "the house is quiet"
  // from "the socket is wedged", which is the case EventSource cannot detect about itself.
  const recycle = next === "live" && msSinceStream > STREAM_STALE_MS;
  return { state: next, recycle };
}
```

Its required behaviour, which `verify.sh` asserts as a table:

| state | pollOk | pollFails | msSinceStream | → state | → recycle |
|---|---|---|---|---|---|
| live | true  | 0 | 1000  | live | false |
| live | false | 1 | 1000  | live | false |
| live | false | 2 | 1000  | live | false |
| live | false | 3 | 1000  | sim  | false |
| sim  | true  | 0 | 1000  | live | false |
| live | true  | 0 | 60000 | live | **true** |
| sim  | false | 9 | 60000 | sim  | false |

Row 2 and 3 are AC1 (a blip must not flip the display). Row 5 is AC3 — recovery is immediate,
only failure is damped. The last row matters most: **a wedged stream is never diagnosed while
the collector is unreachable**, because then silence is expected and recycling would just churn.

The queue admission is pure too, for the same reason:

```js
// Pure. Returns the queue with ev appended, oldest dropped past max.
function txAdmit(queue, ev, max) {
  const out = queue.concat([ev]);
  return out.length > max ? out.slice(out.length - max) : out;
}
```

## 7. Norms · [N]

- Vanilla JS in the existing inline script. Match the file's existing comment voice: say *why*,
  and name the real failure that motivated the code.
- No new globals beyond those in §3. No libraries, no build step.
- Timers must be cleared when they are replaced. A recycle must not leave an old `EventSource`
  or interval running.
- `feedNext` and `txAdmit` must be **pure functions of their arguments** — no globals beyond the
  constants, no DOM, no timers. The gate executes them (§11); an impure function cannot be
  tested, and untestable is how the last three specs shipped defects.
- The status affordance already exists in the DOM (the `live` class and the feed pill). Extend
  it; do not invent a second status widget somewhere else on the page.

## 8. Safeguards · [S]

Non-negotiable. Each is asserted in `verify.sh`.

1. **Never claim live while showing invented data.** `feedState === 'sim'` and the sim generator
   running are the same condition, and the badge must say so.
2. **No unbounded growth.** `txQueue` is capped; on overflow drop oldest and keep the newest.
   A page open for a week must not accumulate.
3. **No reconnect storm.** Recycles back off (3s → 30s cap) and never run more than one
   `EventSource` at a time.
4. **Never require a refresh.** No code path may leave the page permanently degraded once the
   collector is reachable again.

## 9. Task breakdown · [O]

See `tasks.txt`. Six tasks, each touching only `harness-console/index.html`.

## 10. Acceptance criteria (EARS) · [O]

1. **Where** `/api/state` fails fewer than 3 consecutive times, the page **shall** keep
   `feedState` at `live` (transient blips do not flip the display).
2. **When** `/api/state` has failed 3 consecutive times, the page **shall** set `feedState` to
   `sim` and start the simulated generator.
3. **When** `/api/state` succeeds after any failure, the page **shall** return to `live` on that
   first success — recovery is immediate, only failure is damped.
4. **While** `feedState` is `live` and no SSE frame has reached `onmessage` for
   `STREAM_STALE_MS`, the page **shall** close the existing `EventSource` and open a new one.
5. **When** the document becomes visible after being hidden, the page **shall** immediately
   revalidate rather than waiting for the next interval tick.
6. **While** `feedState` is `sim`, the page **shall** display an unmistakable simulated
   indicator, distinct in text from the live indicator.
7. **Where** more than one event is accepted within `TX_MIN_GAP_MS`, the page **shall** release
   them from `txQueue` spaced by at least that gap.
8. **While** `txQueue` length exceeds `TX_QUEUE_MAX`, the page **shall** discard oldest entries.
9. **Where** consecutive stream recycles occur, each delay **shall** be at least the previous
   one, capped at 30000 ms.

## 11. Verification (the harness)

`./specs/pulse-live-feed/verify.sh` — STATIC tier, offline, presence-gated (a check for a
not-yet-written identifier is `pend`, never `FAIL`, so the gate is runnable after every task).

LIVE tier — **not** loop-gated, performed by a human after merge:

- Open the page, `sudo docker restart harness-console` on the Beelink; the page returns to LIVE
  on its own within ~30s and no refresh is used.
- Put the laptop to sleep with the page open, wake it, and confirm the feed resumes unattended.
- Block the collector (stop the container); confirm the page visibly says SIMULATED rather than
  continuing to look healthy.

## 12. Open questions

- The collector cannot currently tell the page that **Matrix itself** is unreachable (its
  `busState` is internal). A collector that is up but whose `/sync` is failing will look like a
  quiet house. Closing that needs a `beelink-ansible` change and is deliberately **out of scope
  here** — file it as a follow-up spec against that repo.
