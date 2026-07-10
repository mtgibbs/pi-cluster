#!/usr/bin/env -S node --no-warnings
// gen-edges.mjs — extract the repo's REFERENCE GRAPH (the "knowledge cloud"
// edge index). The repo map (gen-repomap.mjs) tells a model what files exist;
// this tells it how they're CONNECTED — the thing multi-hop questions actually
// traverse (see docs/research/codemap-serena-token-efficiency.md, multi-hop
// round: map savings vanish because structure != references).
//
//   node gen-edges.mjs [root] [--json graph.json]   # text index to stdout
//
// Edge types extracted (regex over raw file text — no YAML parser needed):
//   secret:<name>       secretName / secretKeyRef targets
//   1p:<item/field>     ExternalSecret remoteRef keys (the 1Password source)
//   pvc:<name>          persistentVolumeClaim claimName
//   svc:<dns>           in-cluster service calls (*.ns.svc[.cluster.local])
//   dependsOn:<name>    Flux Kustomization ordering
//   imagepolicy:<ref>   Flux image-automation markers on deployments
//   nfs:<server:path>   NFS mounts
//   backs-up:<ns_pvc>   PVCS="..." lists inside backup shell scripts
//   route:<cidr>        Tailscale advertiseRoutes
//   doc:<path>          repo file paths mentioned in markdown docs
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const args = process.argv.slice(2);
const root = args.find((a) => !a.startsWith("--")) ?? process.cwd();
const jsonIdx = args.indexOf("--json");
const jsonOut = jsonIdx >= 0 ? args[jsonIdx + 1] : null;
const budgetIdx = args.indexOf("--budget");
const BUDGET = budgetIdx >= 0 ? Number(args[budgetIdx + 1]) : 2500; // tokens; manifest edges are never pruned

const SKIP_DIRS = new Set([".git", "node_modules", "results", ".worktrees"]);
function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(join(dir, e.name), out); }
    else if (/\.(ya?ml|md|sh|mjs|js)$/.test(e.name)) out.push(join(dir, e.name));
  }
  return out;
}

// [edge type, regex (g), capture -> label]
const RULES = [
  ["secret", /secretName:\s*["']?([\w.-]+)/g],
  ["secret", /secretKeyRef:\s*\n\s+name:\s*["']?([\w.-]+)/g],
  ["1p", /remoteRef:\s*\n\s+key:\s*["']?([\w.-]+\/[\w. -]+?)["']?\s*$/gm],
  ["pvc", /claimName:\s*["']?([\w.-]+)/g],
  ["svc", /\b([a-z0-9-]+\.[a-z0-9-]+\.svc(?:\.cluster\.local)?(?:[:/][\w./-]*)?)/g],
  ["dependsOn", /dependsOn:\s*\n((?:\s+-\s+name:\s*[\w.-]+\n?)+)/g],
  ["imagepolicy", /\$imagepolicy["']?\s*:\s*["']?([\w:-]+)/g],
  ["nfs", /server:\s*([\w.-]+)\s*\n\s+path:\s*(\S+)/g],
  ["backs-up", /PVCS="([^"]+)"/g],
  ["route", /advertiseRoutes:\s*\n((?:\s+-\s+[\d./]+\s*(?:#[^\n]*)?\n?)+)/g],
];

const edges = []; // {src, type, target}
const add = (src, type, target) => {
  target = target.trim();
  if (target) edges.push({ src, type, target });
};

for (const file of walk(root)) {
  const rel = relative(root, file);
  let text;
  try { text = readFileSync(file, "utf8"); } catch { continue; }

  if (/\.md$/.test(rel)) {
    // docs edge: any repo file path mentioned in a markdown doc
    for (const m of text.matchAll(/\b((?:clusters|scripts|specs|docs|\.claude)\/[\w./-]+\.\w+)/g))
      add(rel, "doc", m[1]);
    continue;
  }

  for (const [type, re] of RULES) {
    for (const m of text.matchAll(re)) {
      if (type === "dependsOn" || type === "route") {
        for (const item of m[1].matchAll(/-\s+(?:name:\s*)?([\w.\/-]+)/g)) add(rel, type, item[1]);
      } else if (type === "backs-up") {
        for (const pvc of m[1].split(/\s+/)) add(rel, type, pvc);
      } else if (type === "nfs") {
        add(rel, type, `${m[1]}:${m[2]}`);
      } else {
        add(rel, type, m[1]);
      }
    }
  }
}

// Dedupe, drop self-references and doc-edge noise (a doc citing itself)
const seen = new Set();
const clean = edges.filter((e) => {
  if (e.type === "doc" && (e.target === e.src || !/\.(ya?ml|sh|mjs|js|md)$/.test(e.target))) return false;
  const k = `${e.src}|${e.type}|${e.target}`;
  if (seen.has(k)) return false;
  seen.add(k);
  return true;
});

// Text render: one line per source file, edges grouped inline. Budget prunes
// doc-mention edges only (historical recaps first, then cap, then drop all
// doc edges) — manifest reference edges are the product and never pruned.
function renderEdges(list) {
  const bySrc = new Map();
  for (const e of list) {
    if (!bySrc.has(e.src)) bySrc.set(e.src, []);
    bySrc.get(e.src).push(`${e.type}:${e.target}`);
  }
  return [...bySrc].sort(([a], [b]) => a.localeCompare(b))
    .map(([src, es]) => `${src} -> ${es.join(" ")}`).join("\n");
}
const tok = (s) => Math.ceil(s.length / 4);
let kept = clean;
const PRUNES = [
  (es) => es.filter((e) => !(e.type === "doc" && /^docs\/(recaps|session-recaps)\//.test(e.src))),
  (es) => {
    const perSrc = new Map();
    return es.filter((e) => {
      if (e.type !== "doc") return true;
      const n = (perSrc.get(e.src) ?? 0) + 1;
      perSrc.set(e.src, n);
      return n <= 4;
    });
  },
  (es) => es.filter((e) => e.type !== "doc"),
];
for (const prune of PRUNES) {
  if (tok(renderEdges(kept)) <= BUDGET) break;
  kept = prune(kept);
}
const text = renderEdges(kept);

if (jsonOut) {
  const nodes = [...new Set(clean.flatMap((e) => [e.src, `${e.type}:${e.target}`]))];
  writeFileSync(jsonOut, JSON.stringify({ generated_from: "gen-edges.mjs", nodes, edges: clean }, null, 1));
  process.stderr.write(`graph json: ${clean.length} edges, ${nodes.length} nodes -> ${jsonOut}\n`);
}
process.stderr.write(`edge-index: ${kept.length}/${clean.length} edges kept, ~${tok(text)} tokens (budget ${BUDGET})\n`);
process.stdout.write(text + "\n");
