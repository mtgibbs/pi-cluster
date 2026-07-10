#!/usr/bin/env -S node --no-warnings
// run-bench.mjs — run the repo-navigation Q&A benchmark through the local
// coding model (via `oc run`) and meter token usage from opencode's session DB.
//
//   node run-bench.mjs --arm A [--reps 1] [--only q1,q5] [--timeout 300] [--budget 1500]
//
// Arms:
//   A  baseline — question only; the model navigates with its normal tools
//   B  repo-map — a token-budgeted structural map (gen-repomap.mjs) is
//      prepended to the prompt as a navigation index
//   C  serena   — reserved; requires uv/python in the harness image (not baked yet)
//
// Each trial appends one JSON line to results/results.jsonl:
//   {ts, arm, qid, rep, pass, rc, dur_ms, tokens_{input,output,reasoning,
//    cache_read,cache_write}, model, session_id, map_tokens, out_tail}
import { execFileSync, execSync, spawn } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync, readdirSync, unlinkSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = execSync("git rev-parse --show-toplevel", { cwd: HERE, encoding: "utf8" }).trim();
const DB_PATH = join(process.env.HOME, ".local/share/opencode/opencode.db");
const RESULTS = join(HERE, "results/results.jsonl");

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : dflt;
};
const ARM = opt("arm", "");
const REPS = Number(opt("reps", 1));
const ONLY = opt("only", "").split(",").filter(Boolean);
const TIMEOUT = Number(opt("timeout", 300));
const BUDGET = Number(opt("budget", 2000));
const QFILE = opt("qfile", "questions.jsonl");
const TAG = opt("tag", ""); // free-form variant label (e.g. edge-index v2) recorded per row
if (!["A", "B", "G"].includes(ARM)) {
  console.error("usage: run-bench.mjs --arm A|B|G [--reps N] [--only q1,q2] [--qfile questions-multihop.jsonl] [--timeout secs] [--budget tokens]");
  console.error("arms: A baseline, B repo-map, G repo-map + edge index (knowledge graph); C/serena reserved until uv+python are baked into the harness image");
  process.exit(2);
}

const questions = readFileSync(join(HERE, QFILE), "utf8")
  .split("\n").filter(Boolean).map((l) => JSON.parse(l))
  .filter((q) => !ONLY.length || ONLY.includes(q.id));

let map = "", mapTokens = 0, edgeIndex = "", edgeTokens = 0;
if (ARM === "B" || ARM === "G") {
  map = execFileSync("node", [join(HERE, "gen-repomap.mjs"), ROOT, "--budget", String(BUDGET)], {
    encoding: "utf8", stdio: ["ignore", "pipe", "inherit"],
  });
  mapTokens = Math.ceil(map.length / 4);
}
if (ARM === "G") {
  edgeIndex = execFileSync("node", [join(HERE, "gen-edges.mjs"), ROOT], {
    encoding: "utf8", stdio: ["ignore", "pipe", "inherit"],
  });
  edgeTokens = Math.ceil(edgeIndex.length / 4);
}

const PREAMBLE =
  "Answer the following question about this repository by finding the answer in the repo files. " +
  "Be concise and include the literal value, filename, or expression asked for.";
const MAP_BLOCK = (m) =>
  "Below is a compact map of this repository. Use it to open the right files directly " +
  "instead of searching broadly.\n<repo-map>\n" + m + "</repo-map>\n\n";
// Two instruction variants for the edge index (--edge-instr):
//   follow  (v1/v2 default) — "follow chains directly instead of opening each
//           link". This wording CAUSED the m4 failure class: the model quoted
//           the index as an authority and never verified in the source.
//   verify  — index is a pointer, not a source; verify literals before answering.
const EDGE_INSTR = {
  follow:
    "Use it to follow cross-file chains directly instead of opening each link in the chain.",
  verify:
    "Use it to decide which file(s) to open. The index is derived and abbreviated — verify any " +
    "literal you report (names, values, schedules) by reading the source file before answering.",
};
const EDGE_INSTR_KEY = opt("edge-instr", "follow");
const EDGE_BLOCK = (e) =>
  "Below is a reference index of this repository: for each file, the secrets, 1Password items " +
  "(1p:item/field), PVCs, in-cluster services, Flux dependencies, image policies, NFS paths, and " +
  "backup targets it references. " + EDGE_INSTR[EDGE_INSTR_KEY] +
  "\n<edge-index>\n" + e + "</edge-index>\n\n";

const db = new DatabaseSync(DB_PATH, { readOnly: true });
const maxCreated = () =>
  db.prepare("select coalesce(max(time_created),0) m from session").get().m;
const sessionAfter = (t) =>
  db.prepare(
    "select id, model, cost, tokens_input, tokens_output, tokens_reasoning, " +
    "tokens_cache_read, tokens_cache_write from session where time_created > ? " +
    "order by time_created desc limit 1"
  ).get(t);

mkdirSync(join(HERE, "results"), { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// opencode `run` reliably HANGS after printing its answer (remote MCP
// connections keep the process alive), so a fixed timeout charges every trial
// the full wait. Instead: idle-kill after IDLE_SECS with no new output, hard
// cap at --timeout, and record time-to-last-output as the honest duration.
// Default 120s: big uncached prefills on the Beelink can stall output for
// minutes, and an idle-kill mid-prefill records a false FAIL.
const IDLE_SECS = Number(process.env.BENCH_IDLE_SECS ?? 120);
function runOnce(prompt) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const child = spawn("opencode", ["run", prompt], {
      cwd: ROOT, stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "", killed = null, lastOut = Date.now(), idleTimer, hardTimer;
    const kill = (why) => {
      killed = why;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 3000).unref();
    };
    const bump = () => {
      lastOut = Date.now();
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => kill("idle"), IDLE_SECS * 1000);
    };
    bump();
    hardTimer = setTimeout(() => kill("hard"), TIMEOUT * 1000);
    child.stdout.on("data", (d) => { out += d; bump(); });
    child.stderr.on("data", (d) => { out += d; bump(); });
    child.on("close", (code) => {
      clearTimeout(idleTimer); clearTimeout(hardTimer);
      cleanBunLitter();
      resolve({ out, rc: code ?? 0, killed, dur_ms: Date.now() - t0, dur_active_ms: lastOut - t0 });
    });
  });
}

// opencode is a Bun binary: every spawn extracts a ~5.4MB native .so into /tmp
// under a random hidden name and never removes it. 48 trials filled the harness
// container's 256M tmpfs — sweep the litter after each trial. Safe because the
// bench requires no concurrent opencode sessions (see README).
function cleanBunLitter() {
  try {
    for (const f of readdirSync("/tmp")) {
      if (/^\.[0-9a-f]{16}-\d{8}\.(so|node)$/.test(f)) {
        try { unlinkSync(`/tmp/${f}`); } catch {}
      }
    }
  } catch {}
}

for (const q of questions) {
  for (let rep = 1; rep <= REPS; rep++) {
    const before = maxCreated();
    const prompt =
      PREAMBLE + "\n\n" +
      (map ? MAP_BLOCK(map) : "") +
      (edgeIndex ? EDGE_BLOCK(edgeIndex) : "") +
      "Question: " + q.q;
    const { out, rc, killed, dur_ms, dur_active_ms } = await runOnce(prompt);

    // Wait for the session row AND for its token totals to flush — an idle-kill
    // can land before opencode persists token accounting (rows with tokens=0).
    let ses = null;
    for (let i = 0; i < 30; i++) {
      ses = sessionAfter(before);
      if (ses && (ses.tokens_input > 0 || ses.tokens_cache_read > 0)) break;
      await sleep(500);
    }
    const model = ses?.model ? JSON.parse(ses.model).id : null;
    // grade may be a single regex or an array (multi-hop: ALL must match, so a
    // lucky endpoint guess without the traversed chain still fails)
    const grades = Array.isArray(q.grade) ? q.grade : [q.grade];
    const pass = grades.every((g) => new RegExp(g).test(out));

    const row = {
      ts: new Date().toISOString(), arm: ARM, tag: TAG || undefined, qid: q.id, rep, pass, rc, killed, dur_ms, dur_active_ms,
      tokens_input: ses?.tokens_input ?? null, tokens_output: ses?.tokens_output ?? null,
      tokens_reasoning: ses?.tokens_reasoning ?? null,
      tokens_cache_read: ses?.tokens_cache_read ?? null,
      tokens_cache_write: ses?.tokens_cache_write ?? null,
      model, session_id: ses?.id ?? null, map_tokens: mapTokens, edge_tokens: edgeTokens,
      out_tail: out.trim().slice(-300),
    };
    appendFileSync(RESULTS, JSON.stringify(row) + "\n");
    console.log(
      `${q.id} rep${rep} arm=${ARM} ${pass ? "PASS" : "FAIL"} ` +
      `in=${row.tokens_input} out=${row.tokens_output} cache=${row.tokens_cache_read} ` +
      `${Math.round(dur_active_ms / 1000)}s active${killed ? ` (${killed}-killed)` : ""}`
    );
  }
}
