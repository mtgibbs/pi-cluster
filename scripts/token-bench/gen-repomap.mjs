#!/usr/bin/env -S node --no-warnings
// gen-repomap.mjs — emit a compact, token-budgeted structural map of the repo
// for injection into a local-model prompt (the "passive repo-map" pattern from
// docs/research/codemap-serena-token-efficiency.md).
//
//   node gen-repomap.mjs [root] [--budget 1500] [--level N]
//
// Detail levels (auto-degrades largest-first until the map fits the budget):
//   3  yaml kind/name per doc, md h1+h2, script first-comment
//   2  yaml kinds only, md h1 only
//   1  filenames only
//   0  directories with file counts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, basename } from "node:path";

const args = process.argv.slice(2);
const root = args.find((a) => !a.startsWith("--")) ?? process.cwd();
const flag = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? Number(args[i + 1]) : dflt;
};
const BUDGET = flag("budget", 2000); // approx tokens; chars/4 heuristic
const FORCE_LEVEL = flag("level", -1);

const SKIP_DIRS = new Set([".git", "node_modules", "results", ".worktrees", ".next", "public"]);
const SKIP_FILES = /\.(png|jpg|jpeg|gif|ico|woff2?|ttf|zip|gz|db|svg|lock)$|package-lock\.json$/i;

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) {
      if (!SKIP_DIRS.has(e.name)) walk(join(dir, e.name), out);
    } else if (!SKIP_FILES.test(e.name)) {
      out.push(join(dir, e.name));
    }
  }
  return out;
}

function readHead(file, bytes = 16384) {
  try {
    return readFileSync(file, "utf8").slice(0, bytes);
  } catch {
    return "";
  }
}

function describeYaml(file, level) {
  const docs = readHead(file, 32768).split(/^---\s*$/m);
  const parts = [];
  for (const d of docs) {
    const kind = d.match(/^kind:\s*(\S+)/m)?.[1];
    if (!kind) continue;
    if (level >= 3) {
      // first name: after metadata: — cheap regex, good enough for a map
      const name = d.match(/^metadata:\s*\n(?:.*\n)*?\s+name:\s*(\S+)/m)?.[1];
      parts.push(name ? `${kind}/${name}` : kind);
    } else {
      parts.push(kind);
    }
  }
  return parts.length ? [...new Set(parts)].join(", ") : "";
}

function describeMd(file, level) {
  const head = readHead(file);
  const h1 = head.match(/^#\s+(.+)$/m)?.[1] ?? "";
  if (level < 3) return h1;
  const h2s = [...head.matchAll(/^##\s+(.+)$/gm)].map((m) => m[1]).slice(0, 6);
  return h2s.length ? `${h1} [${h2s.join(" | ")}]` : h1;
}

function describeScript(file) {
  const lines = readHead(file, 2048).split("\n").slice(0, 6);
  for (const l of lines) {
    const m = l.match(/^(?:#|\/\/)\s*(?!!)(.{5,100})/);
    if (m && !m[1].startsWith("!")) return m[1].trim();
  }
  return "";
}

function describeTs(file, level) {
  const head = readHead(file, 32768);
  const names = [...head.matchAll(
    /export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type|enum)\s+(\w+)/g
  )].map((m) => m[1]);
  if (!names.length && /export\s+default/.test(head)) names.push("(default)");
  const max = level >= 3 ? 8 : 3;
  return names.length ? `exports: ${[...new Set(names)].slice(0, max).join(", ")}` : "";
}

function describe(file, level) {
  if (level <= 1) return "";
  if (/\.ya?ml$/.test(file)) return describeYaml(file, level);
  if (/\.md$/.test(file)) return describeMd(file, level);
  if (/\.(ts|tsx|jsx)$/.test(file)) return describeTs(file, level);
  if (/\.(sh|mjs|js|py)$/.test(file)) return describeScript(file) || describeTs(file, level);
  return "";
}

// Per-file degradation (largest entries demoted first), then whole-directory
// collapse (largest dirs first) — keeps detail where it's cheap instead of
// degrading the whole map uniformly.
const files = walk(root).sort();
const entries = files.map((f) => {
  const rel = relative(root, f);
  const dir = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : ".";
  const texts = {};
  for (const l of [3, 2, 1]) {
    const desc = describe(f, l);
    texts[l] = desc ? `  ${basename(f)} — ${desc}` : `  ${basename(f)}`;
  }
  return { dir, texts, level: FORCE_LEVEL >= 0 ? FORCE_LEVEL || 1 : 3, collapsed: false };
});

const dirs = () => {
  const m = new Map();
  for (const e of entries) {
    if (!m.has(e.dir)) m.set(e.dir, []);
    m.get(e.dir).push(e);
  }
  return m;
};

// Boilerplate names every service dir has — omit from collapsed-dir summaries
// so the distinctive files (the actual navigation signal) survive collapse.
const COMMON = /^(deployment|service|ingress|namespace|kustomization|external-secret|configmap|rbac|pvc|nfs-pv|helmrelease|servicemonitor)\.ya?ml$/;

function render() {
  const lines = [];
  for (const [dir, es] of [...dirs()].sort(([a], [b]) => a.localeCompare(b))) {
    if (es[0].collapsed) {
      const distinct = es
        .map((e) => e.texts[1].trim())
        .filter((n) => !COMMON.test(n))
        .slice(0, 6);
      lines.push(
        distinct.length && distinct.length < es.length
          ? `${dir}/ (${es.length} files incl. ${distinct.join(", ")})`
          : `${dir}/ (${es.length} files)`
      );
    } else {
      lines.push(`${dir}/`);
      for (const e of es) lines.push(e.texts[e.level]);
    }
  }
  return lines.join("\n");
}

const tokens = () => Math.ceil(render().length / 4);

if (FORCE_LEVEL < 0) {
  // Phase 1: demote the fattest individual entries 3 -> 2 -> 1.
  while (tokens() > BUDGET) {
    const cand = entries
      .filter((e) => e.level > 1)
      .sort((a, b) => b.texts[b.level].length - a.texts[a.level].length)[0];
    if (!cand) break;
    cand.level--;
  }
  // Phase 2: still over? Collapse whole directories to a count line —
  // low-navigation-value dirs (recaps, specs, skills) first, manifests last.
  const keepValue = (dir) =>
    /^(clusters|components|pages|hooks|lib|context|src)\b/.test(dir) ? 3
    : /^(scripts|data|docs\/adr)/.test(dir) ? 2
    : /^docs/.test(dir) ? 1 : 0;
  while (tokens() > BUDGET) {
    const cand = [...dirs()]
      .filter(([, es]) => !es[0].collapsed && es.length > 1)
      .sort(([da, a], [db, b]) => {
        const v = keepValue(da) - keepValue(db);
        if (v) return v; // collapse lower-value dirs first
        return (
          b.reduce((s, e) => s + e.texts[e.level].length, 0) -
          a.reduce((s, e) => s + e.texts[e.level].length, 0)
        );
      })[0];
    if (!cand) break;
    for (const e of cand[1]) e.collapsed = true;
  }
}

process.stderr.write(`repo-map: ~${tokens()} tokens (budget ${BUDGET})\n`);
process.stdout.write(render() + "\n");
