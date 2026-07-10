#!/usr/bin/env -S node --no-warnings
// report.mjs — aggregate results/results.jsonl into per-arm and per-question tables.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const rows = readFileSync(join(HERE, "results/results.jsonl"), "utf8")
  .split("\n").filter(Boolean).map((l) => JSON.parse(l));

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN);
const median = (xs) => {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};
const fmt = (n) => (Number.isFinite(n) ? Math.round(n).toLocaleString() : "-");

function summarize(group) {
  const g = {};
  for (const r of group) (g[r.key] ??= []).push(r);
  return Object.entries(g).map(([key, rs]) => ({
    key, n: rs.length,
    pass: `${rs.filter((r) => r.pass).length}/${rs.length}`,
    "in(med)": fmt(median(rs.map((r) => r.tokens_input ?? NaN))),
    "cache(med)": fmt(median(rs.map((r) => r.tokens_cache_read ?? NaN))),
    "out(med)": fmt(median(rs.map((r) => r.tokens_output ?? NaN))),
    "ctx=in+cache(mean)": fmt(mean(rs.map((r) => (r.tokens_input ?? 0) + (r.tokens_cache_read ?? 0)))),
    "dur_s(med)": fmt(median(rs.map((r) => (r.dur_active_ms ?? r.dur_ms) / 1000))),
  }));
}

const tier = (r) => (r.qid.startsWith("m") ? "multi" : "single");
const armKey = (r) => `arm ${r.arm}${r.tag ? "." + r.tag : ""}`;
console.log("\n== By arm x tier ==");
console.table(summarize(rows.map((r) => ({ ...r, key: `${armKey(r)} (${tier(r)}-hop)` }))));
console.log("== By question x arm ==");
console.table(summarize(rows.map((r) => ({ ...r, key: `${r.qid}/${r.arm}` }))));
const fails = rows.filter((r) => !r.pass);
if (fails.length) {
  console.log("== Failures ==");
  for (const f of fails) console.log(`${f.qid}/${f.arm} rep${f.rep} rc=${f.rc}: ...${f.out_tail.slice(-160)}`);
}
