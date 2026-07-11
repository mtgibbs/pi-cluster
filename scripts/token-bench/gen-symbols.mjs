#!/usr/bin/env -S node --no-warnings
// gen-symbols.mjs — extract a SYMBOL-LEVEL component graph from TS/TSX code:
// how classes and components actually compose, one level below gen-edges.mjs's
// file->file import graph (see docs/research/codemap-serena-token-efficiency.md).
//
//   node gen-symbols.mjs [root] [--budget 3000] [--json graph.json]
//
// Per file, one line, leading with the EXPORTED SYMBOL IDENTITIES (v2 lesson:
// put real names on the sheet; file path second):
//   exports    name(kind[,props=Type ext Base])  kind: component|hook|context|class|type|fn|const
//   renders    JSX composition — Component<-resolved/path.tsx, or Pkg(npm-pkg)
//   provides   <XContext.Provider> rendered here (distinguishes provider from consumer)
//   hooks      custom-hook calls (React built-ins elided) — useX<-defining/file
//   uses       non-rendered imported symbols — {A,B}<-resolved/path
//   reexports  barrel edges — {A,B}<-resolved/path (the ms5 chain, made explicit)
//   api        internal /api/ endpoints fetched at runtime
import { readdirSync, readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { join, relative, dirname, resolve } from "node:path";

const args = process.argv.slice(2);
const root = resolve(args.find((a) => !a.startsWith("--")) ?? process.cwd());
const opt = (name) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : null;
};
const BUDGET = Number(opt("budget") ?? 3000);
const jsonOut = opt("json");

const SKIP_DIRS = new Set([".git", "node_modules", ".next", "public", "results", ".worktrees"]);
function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(join(dir, e.name), out); }
    else if (/\.(tsx?|jsx?|mjs)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(join(dir, e.name));
  }
  return out;
}

// Resolve a relative import specifier to an actual repo file (extension and
// index-file resolution) so barrel hops land on the real defining file.
function resolveImport(fromFile, spec) {
  if (!spec.startsWith(".")) return null; // package import
  const base = resolve(dirname(fromFile), spec);
  const cands = [base, `${base}.ts`, `${base}.tsx`, `${base}.js`, `${base}.jsx`,
                 join(base, "index.ts"), join(base, "index.tsx")];
  // TS NodeNext style: `./x.js` in source actually names `./x.ts(x)` on disk
  if (/\.js$/.test(base)) cands.push(base.replace(/\.js$/, ".ts"), base.replace(/\.js$/, ".tsx"));
  for (const cand of cands)
    if (existsSync(cand) && statSync(cand).isFile()) return relative(root, cand);
  return relative(root, base); // unresolved: keep the path anyway
}

// import clause -> [names]; "Foo" | "{ A, B as C }" | "* as ns" | combinations
function parseClause(clause) {
  const names = [];
  const braces = clause.match(/\{([^}]*)\}/);
  if (braces) {
    for (const part of braces[1].split(","))
      { const n = part.replace(/\btype\b/, "").trim().split(/\s+as\s+/)[0].trim(); if (n) names.push(n); }
  }
  const outer = clause.replace(/\{[^}]*\}/, "").replace(/\btype\b/, "");
  const def = outer.match(/^\s*(\w+)/)?.[1];
  if (def) names.push(def);
  const ns = outer.match(/\*\s+as\s+(\w+)/)?.[1];
  if (ns) names.push(ns);
  return names;
}

const REACT_HOOKS = new Set(["useState", "useEffect", "useMemo", "useRef", "useCallback",
  "useContext", "useLayoutEffect", "useReducer", "useId", "useTransition",
  "useDeferredValue", "useImperativeHandle", "useSyncExternalStore", "useDebugValue"]);

const files = [];
for (const abs of walk(root).sort()) {
  const rel = relative(root, abs);
  let text;
  try { text = readFileSync(abs, "utf8"); } catch { continue; }

  // --- imports: symbol -> defining file (or package name) ---
  const importOf = new Map(); // symbol -> {path, pkg}
  for (const m of text.matchAll(/import\s+(?:type\s+)?([^'"]+?)\s+from\s+['"]([^'"]+)['"]/g)) {
    const target = resolveImport(abs, m[2]);
    for (const n of parseClause(m[1]))
      importOf.set(n, target ? { path: target } : { pkg: m[2] });
  }
  // dynamic imports: const { fn } = await import('./x.js') — lazy-loaded deps
  // are still composition edges (found via pi-cluster-mcp's touch_nas_path)
  const dynImports = new Map(); // resolved path -> true
  for (const m of text.matchAll(/import\s*\(\s*['"](\.[^'"]+)['"]\s*\)/g)) {
    const target = resolveImport(abs, m[1]);
    if (target) dynImports.set(target, true);
  }

  // --- exported symbols with kind ---
  const exports = []; // {name, kind, propsType, ext}
  const seen = new Set();
  const addExport = (name, kind) => {
    if (!name || seen.has(name)) return;
    seen.add(name);
    exports.push({ name, kind });
  };
  for (const m of text.matchAll(
    /export\s+(?:default\s+)?(?:abstract\s+)?(?:async\s+)?(function|class|const|let|interface|type|enum)\s+(\w+)/g
  )) {
    const [, kw, name] = m;
    const kind =
      /^use[A-Z]/.test(name) ? "hook"
      : kw === "class" ? "class"
      : kw === "interface" || kw === "type" || kw === "enum" ? "type"
      : /^[A-Z]/.test(name) && /\.(tsx|jsx)$/.test(rel) ? "component"
      : kw === "function" ? "fn" : "const";
    addExport(name, kind);
  }
  const dflt = text.match(/export\s+default\s+(\w+)\s*;?\s*$/m)?.[1];
  if (dflt && !["function", "class", "async"].includes(dflt))
    addExport(dflt, /^use[A-Z]/.test(dflt) ? "hook" : /^[A-Z]/.test(dflt) && /\.(tsx|jsx)$/.test(rel) ? "component" : "fn");
  for (const m of text.matchAll(/export\s+\{([^}]*)\}\s*(?!\s*from)/g))
    for (const part of m[1].split(","))
      { const n = part.replace(/\btype\b/, "").trim().split(/\s+as\s+/).pop()?.trim();
        if (n) addExport(n, /^use[A-Z]/.test(n) ? "hook" : /^[A-Z]/.test(n) ? "component" : "fn"); }

  // context definitions upgrade kind
  for (const m of text.matchAll(/(?:const|let)\s+(\w+)\s*=\s*createContext/g)) {
    const e = exports.find((x) => x.name === m[1]);
    if (e) e.kind = "context"; else exports.push({ name: m[1], kind: "context(unexported)" });
  }

  // props interfaces/types (exported or not) + extends chain — prop-flow identity
  const props = []; // {name, ext}
  for (const m of text.matchAll(/(?:interface|type)\s+(\w*Props)\b(?:\s+extends\s+([\w<>,.\s]+?))?\s*[{=]/g))
    props.push({ name: m[1], ext: m[2]?.trim().replace(/\s+/g, " ") });
  // interface/class extends outside *Props (model types)
  const extend = [];
  for (const m of text.matchAll(/(?:interface|class)\s+(\w+)\s+extends\s+([\w<>,.\s]+?)\s*\{/g))
    if (!/Props$/.test(m[1])) extend.push(`${m[1]} ext ${m[2].trim().replace(/\s+/g, " ")}`);

  // --- JSX render + provider edges (only files that can hold JSX) ---
  // Generics guard: a JSX `<` is never immediately preceded by an identifier
  // char; a generic's always is (useSWR<SpotifyData>, useRef<HTMLDivElement>).
  const renders = new Set(), provides = new Set();
  if (/\.(tsx|jsx)$/.test(rel)) {
    for (const m of text.matchAll(/<([A-Z][\w.]*)[\s/>]/g)) {
      if (/[\w$]/.test(text[m.index - 1] ?? "")) continue;
      const tag = m[1];
      if (tag.endsWith(".Provider")) provides.add(tag);
      else if (!tag.includes(".")) renders.add(tag);
    }
  }

  // --- custom hook calls (not React built-ins, not self-defined) ---
  const hooks = new Set();
  for (const m of text.matchAll(/\b(use[A-Z]\w*)\s*[(<]/g))
    if (!REACT_HOOKS.has(m[1]) && !seen.has(m[1])) hooks.add(m[1]);

  // --- barrel re-exports ---
  const reexports = []; // {names, path}
  for (const m of text.matchAll(/export\s+(type\s+)?(?:\{([^}]*)\}|\*)\s*from\s+['"]([^'"]+)['"]/g)) {
    const isType = !!m[1];
    const names = m[2]
      ? m[2].split(",").map((s) => s.replace(/\btype\b/, "").trim().split(/\s+as\s+/)[0].trim()).filter(Boolean)
      : ["*"];
    reexports.push({ names, path: resolveImport(abs, m[3]) ?? m[3] });
    for (const n of names)
      if (n !== "*")
        addExport(n, isType ? "type" : /^use[A-Z]/.test(n) ? "hook"
          : /^[A-Z0-9_]+$/.test(n) ? "const" : /^[A-Z]/.test(n) ? "component" : "fn");
  }

  // --- internal API fetches ---
  const api = new Set();
  for (const m of text.matchAll(/['"`](\/api\/[\w/[\].-]+)['"`]/g)) api.add(m[1]);

  // non-rendered, non-hook imported symbols actually referenced = "uses"
  const used = new Map(); // path/pkg -> [names]
  for (const [name, src] of importOf) {
    if (renders.has(name) || hooks.has(name)) continue;
    if (src.pkg) continue; // package types/fns are noise (cn, React, swr fetchers)
    const refs = text.split(name).length - 1;
    if (refs < 2) continue; // imported but never referenced again
    const key = src.path;
    if (!used.has(key)) used.set(key, []);
    used.get(key).push(name);
  }

  for (const [path] of dynImports) {
    if (!used.has(path)) used.set(path, []);
    used.get(path).push("(dynamic)");
  }
  files.push({ rel, exports, props, extend, renders, provides, hooks, reexports, api, used, importOf });
}

// Cross-file: attach defining path to rendered components and called hooks.
const definers = new Map(); // symbol -> rel path defining it (first wins; barrels overwritten by real definers later is fine)
for (const f of files) for (const e of f.exports) if (!definers.has(e.name)) definers.set(e.name, f.rel);

function renderLine(f) {
  const parts = [];
  const exp = f.exports.map((e) => {
    let s = `${e.name}(${e.kind}`;
    const p = f.props.find((pp) => pp.name.toLowerCase().startsWith(e.name.toLowerCase()));
    if (p) s += `,props=${p.name}${p.ext ? ` ext ${p.ext}` : ""}`;
    return s + ")";
  });
  if (exp.length) parts.push(exp.join(" "));
  const orphanProps = f.props.filter((p) => !f.exports.some((e) => p.name.toLowerCase().startsWith(e.name.toLowerCase())));
  for (const p of orphanProps) parts.push(`${p.name}(props${p.ext ? ` ext ${p.ext}` : ""})`);
  for (const x of f.extend) parts.push(`[${x}]`);

  const edge = (name) => {
    const src = f.importOf.get(name);
    if (src?.path) return `${name}<-${src.path}`;
    if (src?.pkg) return `${name}(${src.pkg})`;
    const def = definers.get(name);
    return def && def !== f.rel ? `${name}<-${def}` : name;
  };
  if (f.renders.size) parts.push("renders: " + [...f.renders].map(edge).join(" "));
  if (f.provides.size) parts.push("provides: " + [...f.provides].join(" "));
  if (f.hooks.size) parts.push("hooks: " + [...f.hooks].map(edge).join(" "));
  for (const [path, names] of f.used) parts.push(`uses: {${names.join(",")}}<-${path}`);
  for (const r of f.reexports) parts.push(`reexports: {${r.names.join(",")}}<-${r.path}`);
  if (f.api.size) parts.push("api: " + [...f.api].join(" "));
  return `${f.rel} :: ${parts.join(" | ")}`;
}

const tok = (s) => Math.ceil(s.length / 4);
// Degrade to budget: drop package-sourced render edges first, then "uses" lists.
let lines = files.map(renderLine);
if (tok(lines.join("\n")) > BUDGET) {
  for (const f of files) for (const r of [...f.renders]) if (f.importOf.get(r)?.pkg) f.renders.delete(r);
  lines = files.map(renderLine);
}
if (tok(lines.join("\n")) > BUDGET) {
  for (const f of files) f.used.clear();
  lines = files.map(renderLine);
}
const text = lines.join("\n");

if (jsonOut) {
  const edges = [];
  for (const f of files) {
    for (const r of f.renders) edges.push({ src: f.rel, type: "renders", target: r, targetFile: f.importOf.get(r)?.path ?? definers.get(r) ?? null });
    for (const h of f.hooks) edges.push({ src: f.rel, type: "hook", target: h, targetFile: f.importOf.get(h)?.path ?? definers.get(h) ?? null });
    for (const p of f.provides) edges.push({ src: f.rel, type: "provides", target: p });
    for (const [path, names] of f.used) for (const n of names) edges.push({ src: f.rel, type: "uses", target: n, targetFile: path });
    for (const r of f.reexports) for (const n of r.names) edges.push({ src: f.rel, type: "reexport", target: n, targetFile: r.path });
    for (const a of f.api) edges.push({ src: f.rel, type: "api", target: a });
  }
  writeFileSync(jsonOut, JSON.stringify({ generated_from: "gen-symbols.mjs", edges }, null, 1));
  process.stderr.write(`graph json: ${edges.length} edges -> ${jsonOut}\n`);
}
process.stderr.write(`symbol-map: ${files.length} files, ~${tok(text)} tokens (budget ${BUDGET})\n`);
process.stdout.write(text + "\n");
