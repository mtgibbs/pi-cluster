#!/usr/bin/env node
// ledger.mjs — derive the factory's earn-out evidence table from GitHub. Nothing is hand-kept.
//
//   GITHUB_TOKEN=... node factory/ledger.mjs [owner/repo ...]     (default: mtgibbs/pi-cluster-mcp)
//   node factory/ledger.mjs --json                                 machine-readable rows
//
// Every factory PR carries the `factory` label, a `factory:class-<x>` label and a verdict
// comment ending in `<!-- factory:record {json} -->` (written by factory/steps.py). From
// those plus GitHub's own merge/close facts this prints, per PR: class, factory verdict,
// what the human did, whether that counts as agreement, and whether a later commit on the
// default branch reverted it. Then per class: agreements, disagreements and the current
// run of consecutive agreements — the numbers the README's promotion rules are written in.
//
// Agreement (README "Earning out"):
//   would merge + human merged the exact head the verdict judged  -> agree
//   hold        + human did not merge that head as-is              -> agree
//   would merge + human closed it unmerged                         -> DISAGREE (factory too lax — blocks promotion)
//   hold        + human merged the judged head unchanged           -> disagree (factory too strict)
//   still open, or no verdict yet                                  -> pending
// Token: GITHUB_TOKEN, else `gh auth token`.
import { execSync } from "node:child_process";

const args = process.argv.slice(2);
const asJson = args.includes("--json");
const repos = args.filter((a) => !a.startsWith("--"));
if (!repos.length) repos.push("mtgibbs/pi-cluster-mcp");
const token = process.env.GITHUB_TOKEN || execSync("gh auth token", { encoding: "utf8" }).trim();

async function gh(path) {
  const out = [];
  let url = path.startsWith("http") ? path : `https://api.github.com${path}`;
  while (url) {
    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "User-Agent": "factory-ledger" },
    });
    if (!r.ok) throw new Error(`GET ${url}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
    const body = await r.json();
    if (!Array.isArray(body)) return body;
    out.push(...body);
    const next = (r.headers.get("link") || "").match(/<([^>]+)>;\s*rel="next"/);
    url = next ? next[1] : null;
  }
  return out;
}

function lastRecord(comments) {
  let rec = null;
  for (const c of comments) {
    const m = c.body.match(/<!-- factory:record (\{.*\}) -->/s);
    if (m) {
      try { rec = { ...JSON.parse(m[1]), comment_url: c.html_url, at: c.created_at }; } catch { /* skip malformed */ }
    }
  }
  return rec;
}

async function rowsFor(repo) {
  const prs = await gh(`/repos/${repo}/issues?labels=factory&state=all&per_page=100`);
  const main = (await gh(`/repos/${repo}`)).default_branch;
  const commits = await gh(`/repos/${repo}/commits?sha=${main}&per_page=100`);
  const rows = [];
  for (const issue of prs.filter((i) => i.pull_request)) {
    const pr = await gh(`/repos/${repo}/pulls/${issue.number}`);
    const rec = lastRecord(await gh(`/repos/${repo}/issues/${issue.number}/comments?per_page=100`));
    const labelClass = (issue.labels.map((l) => l.name).find((n) => n.startsWith("factory:class-")) || "").slice(-1).toUpperCase() || "?";
    const merged = Boolean(pr.merged_at);
    const judgedHead = rec?.head || null;
    const mergedUnchanged = merged && judgedHead && pr.head.sha === judgedHead;
    let human = pr.state === "open" ? "open" : merged ? (mergedUnchanged ? "merged as judged" : "merged after changes") : "closed unmerged";
    let agreement = "pending";
    if (rec && pr.state !== "open") {
      if (rec.verdict === "would merge") agreement = mergedUnchanged ? "agree" : merged ? "agree (changed before merge)" : "DISAGREE: factory would merge, human rejected";
      else agreement = mergedUnchanged ? "disagree: factory held, human merged as-is" : "agree";
    }
    const reverted = merged && commits.some((c) => /^Revert\b/i.test(c.commit.message) &&
      (c.commit.message.includes(`#${pr.number}`) || c.commit.message.includes(pr.title)));
    rows.push({
      repo, number: pr.number, url: pr.html_url, title: pr.title, class: rec?.class || labelClass,
      verdict: rec?.verdict || "none", reasons: rec?.reasons || [], human, merged_by: pr.merged_by?.login || null,
      agreement, reverted, run_id: rec?.run_id || null, created_at: pr.created_at,
    });
  }
  return rows.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

const rows = (await Promise.all(repos.map(rowsFor))).flat();
if (asJson) {
  console.log(JSON.stringify(rows, null, 2));
  process.exit(0);
}
console.log("| PR | class | factory verdict | human | agreement | reverted |");
console.log("|--|--|--|--|--|--|");
for (const r of rows) {
  console.log(`| [${r.repo}#${r.number}](${r.url}) | ${r.class} | ${r.verdict} | ${r.human}${r.merged_by ? ` (${r.merged_by})` : ""} | ${r.agreement} | ${r.reverted ? "**yes**" : "no"} |`);
}
console.log("\n| class | decided | agree | disagree | rejected-would-merge | consecutive agreements (latest run) | reverts |");
console.log("|--|--|--|--|--|--|--|");
for (const cls of ["A", "B", "C"]) {
  const decided = rows.filter((r) => r.class === cls && r.agreement !== "pending");
  const agree = decided.filter((r) => r.agreement.startsWith("agree")).length;
  const rejected = decided.filter((r) => r.agreement.startsWith("DISAGREE")).length;
  let streak = 0;
  for (const r of [...decided].reverse()) { if (r.agreement.startsWith("agree") && !r.reverted) streak++; else break; }
  const reverts = rows.filter((r) => r.class === cls && r.reverted).length;
  console.log(`| ${cls} | ${decided.length} | ${agree} | ${decided.length - agree} | ${rejected} | ${streak} | ${reverts} |`);
}
console.log("\nClass C never earns out, whatever its streak. Promotion also needs the README's preconditions (a judge on a different model, eval scores, positive controls).");
