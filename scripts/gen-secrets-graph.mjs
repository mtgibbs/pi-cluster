#!/usr/bin/env -S node --no-warnings
// gen-secrets-graph.mjs — derive the SECRETS CONNECTIVITY GRAPH from the
// cluster manifests, so an agent can walk "what credential connects to what"
// instead of guessing (and re-minting a token that already exists).
//
// Sibling to token-bench/gen-edges.mjs and shares its house idiom: parse YAML
// PER DOCUMENT with regex, no YAML-parser dependency (Node has none built in;
// keeping it regex-only keeps CI dependency-free). Where gen-edges emits a
// terse token-budget nav sheet for the local model, THIS emits a curated
// domain doc for humans + Claude: 1Password item → ExternalSecret → k8s Secret
// → consuming workload, with the shared-identity ("reuse before mint") signal.
//
//   node gen-secrets-graph.mjs [root]            # node index (markdown) to stdout
//   node gen-secrets-graph.mjs [root] --shared   # reuse-lens mermaid to stdout
//   node gen-secrets-graph.mjs [root] --json     # machine graph (JSON) to stdout
//   node gen-secrets-graph.mjs [root] --inject docs/secrets-map.md
//        # rewrite ONLY the block between the generated markers in that file
//        # (idempotent, deterministic bytes — regenerate to kill drift)
//
// The ~10% a manifest-walk CANNOT derive — secrets consumed by HelmRelease
// `values`, Flux `postBuild.substituteFrom`, cert-manager ClusterIssuer refs,
// or app-internal config — is supplied by the curated overlay (default
// docs/secrets-overlay.yaml, override with --overlay). Everything else is
// derived fresh every run.
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const root = args.find((a) => !a.startsWith("--")) ?? "clusters";
const flag = (name, dflt = null) => {
  const i = args.indexOf(name);
  return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : dflt;
};
const overlayPath = flag("--overlay", join(HERE, "..", "docs", "secrets-overlay.yaml"));

const WORKLOAD_KINDS = new Set([
  "Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "Pod", "ReplicaSet",
]);
const SKIP_DIRS = new Set([".git", "node_modules", ".worktrees", ".next"]);

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(join(dir, e.name), out); }
    else if (/\.ya?ml$/.test(e.name)) out.push(join(dir, e.name));
  }
  return out;
}

// ---- tiny overlay parser (flat "key: value" lines under section headers) ----
// avoids a YAML dependency; the overlay is intentionally a flat two-section map.
function parseOverlay(path) {
  const o = { consumers: {}, tier: {}, note: {} };
  if (!path || path === true || !existsSync(path)) return o;
  let section = null;
  for (const raw of readFileSync(path, "utf8").split("\n")) {
    const line = raw.replace(/#.*$/, "").replace(/\s+$/, "");
    if (!line.trim()) continue;
    const head = line.match(/^(\w+):\s*$/);
    if (head) { section = head[1]; continue; }
    const kv = line.match(/^\s+["']?([^"':]+)["']?:\s*(.+?)\s*$/);
    if (kv && section && o[section]) {
      o[section][kv[1].trim()] = kv[2].replace(/^["']|["']$/g, "");
    }
  }
  return o;
}
const overlay = parseOverlay(overlayPath);

// ---- collect ----
const extSecrets = new Map();     // "ns/target" -> {name, ns, target, opItems:Set}
const opItems = new Map();        // item -> Set("ns/esName")
const consumers = new Map();      // "ns/secret" -> Set("kind\twl\thow")

const metaName = (d) => d.match(/^metadata:[ \t]*\n(?:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/m)?.[1];
const metaNs = (d) => d.match(/^metadata:[ \t]*\n(?:[^\n]*\n)*?[ \t]+namespace:[ \t]*["']?([^\s"']+)/m)?.[1] ?? "?";

function collectExternalSecret(d) {
  const ns = metaNs(d), name = metaName(d) ?? "?";
  const target =
    d.match(/^[ \t]+target:[ \t]*\n(?:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/m)?.[1] ?? name;
  const key = `${ns}/${target}`;
  const rec = extSecrets.get(key) ?? { name, ns, target, opItems: new Set() };
  // 1Password refs: any `key: <item>/<field>` (the slash distinguishes a
  // remoteRef key from a plain secretKey). item = part before the first slash.
  for (const m of d.matchAll(/^[ \t]+key:[ \t]*["']?([^\s"'#]+\/[^\s"'#]+)/gm)) {
    const item = m[1].split("/")[0];
    rec.opItems.add(item);
    if (!opItems.has(item)) opItems.set(item, new Set());
    opItems.get(item).add(`${ns}/${name}`);
  }
  extSecrets.set(key, rec);
}

function collectWorkload(d) {
  const ns = metaNs(d), name = metaName(d) ?? "?", kind = d.match(/^kind:[ \t]*(\S+)/m)[1];
  const hits = []; // [secretName, how]
  for (const m of d.matchAll(/secretKeyRef:[ \t]*\n(?:[ \t]+[\w-]+:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/g))
    hits.push([m[1], "env"]);
  for (const m of d.matchAll(/(?<![\w])secretRef:[ \t]*\n(?:[ \t]+[\w-]+:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/g))
    hits.push([m[1], "envFrom"]);
  for (const m of d.matchAll(/[ \t]+secretName:[ \t]*["']?([^\s"']+)/g))
    hits.push([m[1], "volume"]);
  for (const block of d.matchAll(/imagePullSecrets:[ \t]*\n((?:[ \t]+-[ \t]+name:[^\n]+\n?)+)/g))
    for (const m of block[1].matchAll(/-[ \t]+name:[ \t]*["']?([^\s"']+)/g))
      hits.push([m[1], "imagePull"]);
  for (const [secret, how] of hits) {
    const k = `${ns}/${secret}`;
    if (!consumers.has(k)) consumers.set(k, new Set());
    consumers.get(k).add(`${kind}\t${name}\t${how}`);
  }
}

for (const file of walk(root)) {
  let text;
  try { text = readFileSync(file, "utf8"); } catch { continue; }
  for (const d of text.split(/^---\s*$/m)) {
    const kind = d.match(/^kind:[ \t]*(\S+)/m)?.[1];
    if (kind === "ExternalSecret") collectExternalSecret(d);
    else if (WORKLOAD_KINDS.has(kind)) collectWorkload(d);
  }
}

// consumers for a secret = derived (manifest walk) ∪ curated overlay
function consumersFor(ns, target) {
  const derived = [...(consumers.get(`${ns}/${target}`) ?? [])]
    .map((s) => { const [kind, wl, how] = s.split("\t"); return { kind, wl, how }; })
    .sort((a, b) => (a.wl + a.how).localeCompare(b.wl + b.how));
  const curated = overlay.consumers[`${ns}/${target}`];
  return { derived, curated };
}

// ---- stats (always to stderr) ----
const edgeCount = [...consumers.values()].reduce((n, s) => n + s.size, 0);
const sharedCount = [...opItems.values()].filter((s) => s.size > 1).length;
process.stderr.write(
  `[gen-secrets-graph] ExternalSecrets=${extSecrets.size} 1Password-items=${opItems.size} ` +
  `consumer-edges=${edgeCount} shared-items=${sharedCount}\n`
);

// ---- render: reuse-lens mermaid (only items with fan-out > 1) ----
const sid = (s) => "n" + [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7).toString(36);
function sharedMermaid() {
  const shared = [...opItems.keys()].filter((i) => opItems.get(i).size > 1).sort();
  const out = ["```mermaid", "graph LR"];
  const seen = new Set();
  const node = (id, label, stadium = false) => {
    if (seen.has(id)) return; seen.add(id);
    out.push(stadium ? `  ${id}(["${label}"])` : `  ${id}["${label}"]`);
  };
  for (const it of shared) {
    const op = sid(`op/${it}`);
    node(op, `🔑 ${it}`, true);
    for (const { name, ns, target, opItems: its } of [...extSecrets.values()].sort((a, b) =>
      (a.ns + a.target).localeCompare(b.ns + b.target))) {
      if (!its.has(it)) continue;
      const es = sid(`es/${ns}/${name}`);
      node(es, `${name}<br/>(${ns})`);
      out.push(`  ${op} --> ${es}`);
    }
  }
  out.push("```");
  return out.join("\n");
}

// ---- render: walkable node index ----
function tierBadge(item) {
  const t = overlay.tier[item];
  return t ? ` \`${t}\`` : "";
}
function nodeIndex() {
  const out = [];
  out.push("### 1Password items — source of truth (shared = reuse before mint)\n");
  for (const it of [...opItems.keys()].sort()) {
    const es = [...opItems.get(it)].sort();
    const shared = es.length > 1 ? "  ⟵ **SHARED — reuse, do not mint a parallel one**" : "";
    out.push(`- **${it}**${tierBadge(it)} → ${es.length} ExternalSecret(s):${shared}`);
    for (const e of es) out.push(`    - \`${e}\``);
  }
  out.push("\n### ExternalSecret → k8s Secret → consumers\n");
  for (const { name, ns, target, opItems: its } of [...extSecrets.values()].sort((a, b) =>
    (a.ns + a.target).localeCompare(b.ns + b.target))) {
    const { derived, curated } = consumersFor(ns, target);
    out.push(`- **\`${ns}/${name}\`** ← ${[...its].sort().map((i) => `\`${i}\``).join(", ") || "_no op ref found_"}`);
    out.push(`  produces Secret \`${target}\` in \`${ns}\``);
    if (derived.length)
      for (const c of derived) out.push(`    → \`${ns}/${c.wl}\` (${c.kind}, ${c.how})`);
    if (curated) out.push(`    → _${curated}_ (curated: not a pod-spec ref)`);
    if (!derived.length && !curated) out.push(`    → ⚠️ _no consumer found in-repo — verify (app-config wired, or orphaned)_`);
  }
  return out.join("\n");
}

// ---- output ----
if (flag("--json")) {
  const graph = {
    opItems: Object.fromEntries([...opItems].map(([k, v]) => [k, [...v].sort()])),
    externalSecrets: [...extSecrets.values()].map(({ name, ns, target, opItems: i }) => {
      const { derived, curated } = consumersFor(ns, target);
      return { name, ns, target, opItems: [...i].sort(), consumers: derived, curatedConsumer: curated ?? null };
    }),
    stats: { externalSecrets: extSecrets.size, opItems: opItems.size, consumerEdges: edgeCount, shared: sharedCount },
  };
  process.stdout.write(JSON.stringify(graph, null, 2) + "\n");
} else if (flag("--shared")) {
  process.stdout.write(sharedMermaid() + "\n");
} else if (flag("--inject") || flag("--check")) {
  const target = flag("--inject") || flag("--check");
  const BEGIN = "<!-- BEGIN GENERATED:secrets-graph -->";
  const END = "<!-- END GENERATED:secrets-graph -->";
  const block = [
    BEGIN,
    "<!-- Regenerate with: node scripts/gen-secrets-graph.mjs clusters --inject docs/secrets-map.md -->",
    "<!-- Do not hand-edit between these markers; edits are overwritten. Curate roles/tiers ABOVE, and the",
    "     un-derivable consumers (HelmRelease/Flux/ClusterIssuer/app-config) in docs/secrets-overlay.yaml. -->",
    "",
    "## Connectivity graph (auto-derived from `clusters/**`)",
    "",
    `_${extSecrets.size} ExternalSecrets · ${opItems.size} 1Password items · ${edgeCount} consumer edges · ${sharedCount} shared identities. Skeleton is regenerated; the un-derivable consumers come from \`docs/secrets-overlay.yaml\`._`,
    "",
    "### Reuse lens — shared identities and their fan-out",
    "",
    sharedMermaid(),
    "",
    nodeIndex(),
    "",
    END,
  ].join("\n");
  const src = readFileSync(target, "utf8");
  const re = new RegExp(`${BEGIN}[\\s\\S]*?${END}`);
  const next = re.test(src) ? src.replace(re, block) : src.replace(/\s*$/, "\n\n" + block + "\n");
  if (flag("--check")) {
    if (src !== next) {
      process.stderr.write(`[gen-secrets-graph] DRIFT: ${target} is stale.\n` +
        `  Run: node scripts/gen-secrets-graph.mjs clusters --inject ${target}\n`);
      process.exit(1);
    }
    process.stderr.write(`[gen-secrets-graph] ok: ${target} up to date\n`);
  } else {
    writeFileSync(target, next);
    process.stderr.write(`[gen-secrets-graph] injected block into ${target}\n`);
  }
} else {
  process.stdout.write(nodeIndex() + "\n");
}
