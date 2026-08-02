#!/usr/bin/env -S node --no-warnings
// gen-domain-map.mjs — derive the SERVICE DOMAIN MAP from cluster manifests:
// per service (a dir under clusters/pi-k3s/), what it RUNS (workloads+images),
// what it NEEDS (creds, storage), how it's REACHED (ingress), who it TALKS TO
// (in-cluster svc calls), and what must DEPLOY FIRST (Flux dependsOn DAG).
//
// The service lens; docs/secrets-map.md is the credential lens (cross-linked).
// Same house idiom as gen-secrets-graph.mjs / token-bench/gen-edges.mjs: regex
// per YAML document, no YAML-parser dependency (keeps CI dependency-free).
//
//   node gen-domain-map.mjs [root]            # per-service node index (markdown)
//   node gen-domain-map.mjs [root] --deps     # Flux dependsOn DAG (mermaid)
//   node gen-domain-map.mjs [root] --json     # machine graph
//   node gen-domain-map.mjs [root] --inject docs/domain-map.md   # idempotent block rewrite
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const args = process.argv.slice(2);
const root = args.find((a) => !a.startsWith("--")) ?? "clusters/pi-k3s";
const flag = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : null;
};

const WORKLOAD_KINDS = new Set(["Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "Pod"]);
const SKIP_DIRS = new Set([".git", "node_modules", ".worktrees"]);
const PRIVATE_RE = /^ghcr\.io\/mtgibbs\//;

/**
 * Drop the tag/digest from an image reference: `repo:1.2.3` and `repo@sha256:…` both become `repo`.
 *
 * DELIBERATE. This map records TOPOLOGY — what runs where, what it needs, who it calls — and a
 * version number is none of those. Keeping tags made every image bump a map change, and Flux's
 * ImageUpdateAutomation pushes those straight to main with a deploy key, bypassing the PR gate
 * that would regenerate the map. So main carried a stale map and the NEXT, unrelated PR inherited
 * a red `drift` and had to regenerate someone else's bump. That tax was paid twice on 2026-08-02
 * alone (#125, #126).
 *
 * The deployed tag is a property of the CLUSTER, not of this repo, and is better read from the
 * cluster (`get_flux_status`, `describe_resource`) than from a doc that can only ever be a
 * snapshot of one moment. Please don't add tags back to make the map "more complete": it would
 * reintroduce the drift treadmill in exchange for a field that is stale the moment it is written.
 *
 * Registry ports survive — the tag separator is only a `:` AFTER the last `/`, so
 * `registry:5000/img` is untouched while `registry:5000/img:v2` loses just the `:v2`.
 */
function stripTag(image) {
  const at = image.indexOf("@");
  const ref = at === -1 ? image : image.slice(0, at);
  const colon = ref.lastIndexOf(":");
  return colon > ref.lastIndexOf("/") ? ref.slice(0, colon) : ref;
}

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(join(dir, e.name), out); }
    else if (/\.ya?ml$/.test(e.name)) out.push(join(dir, e.name));
  }
  return out;
}
const svcOf = (file) => { // service = first dir segment; null for root-level files (e.g. the top kustomization.yaml)
  const rel = relative(root, file);
  return rel.includes("/") ? rel.split("/")[0] : null;
};

const metaName = (d) => d.match(/^metadata:[ \t]*\n(?:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/m)?.[1];

// service -> aggregated facts
const svc = new Map();
const S = (name) => {
  if (!svc.has(name)) svc.set(name, {
    name, workloads: [], images: new Set(), privateImages: new Set(),
    creds: new Set(), storage: new Set(), declaredPvc: new Set(),
    ingress: new Set(), calls: new Set(),
  });
  return svc.get(name);
};

// Flux DAG: kustomization name -> {dir, dependsOn:[names]}
const flux = new Map();

for (const file of walk(root)) {
  const service = svcOf(file);
  if (!service) continue; // skip root-level aggregation files
  let text; try { text = readFileSync(file, "utf8"); } catch { continue; }
  for (const d of text.split(/^---\s*$/m)) {
    const kind = d.match(/^kind:[ \t]*(\S+)/m)?.[1];
    if (!kind) continue;

    if (kind === "Kustomization" && /kustomize\.toolkit\.fluxcd\.io/.test(d)) {
      const name = metaName(d); if (!name) continue;
      const path = d.match(/^[ \t]+path:[ \t]*["']?(\S+)/m)?.[1];
      const dir = path ? (path.replace(/^\.?\/?clusters\/pi-k3s\/?/, "").replace(/\/$/, "") || null) : null;
      const deps = [];
      const dep = d.match(/dependsOn:[ \t]*\n((?:[ \t]+-[^\n]*\n?)+)/);
      if (dep) for (const m of dep[1].matchAll(/-[ \t]+name:[ \t]*["']?([^\s"']+)/g)) deps.push(m[1]);
      flux.set(name, { dir, dependsOn: deps });
      continue;
    }

    if (WORKLOAD_KINDS.has(kind)) {
      const s = S(service), name = metaName(d) ?? "?";
      if (/__\w+__/.test(name)) continue; // skip kustomize template placeholders (e.g. restore-__APP__)
      // Tag-stripped at the PARSE boundary, so no downstream consumer — node index, --json,
      // private-image detection — can leak a version and put us back on the drift treadmill.
      const imgs = [...d.matchAll(/^[ \t]+image:[ \t]*["']?([^\s"']+)/gm)].map((m) => stripTag(m[1]));
      for (const i of imgs) { s.images.add(i); if (PRIVATE_RE.test(i)) s.privateImages.add(i); }
      s.workloads.push({ kind, name, images: [...new Set(imgs)] });
      // creds consumed
      for (const m of d.matchAll(/secretKeyRef:[ \t]*\n(?:[ \t]+[\w-]+:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/g)) s.creds.add(m[1]);
      for (const m of d.matchAll(/(?<![\w])secretRef:[ \t]*\n(?:[ \t]+[\w-]+:[^\n]*\n)*?[ \t]+name:[ \t]*["']?([^\s"']+)/g)) s.creds.add(m[1]);
      for (const m of d.matchAll(/imagePullSecrets:[ \t]*\n((?:[ \t]+-[ \t]+name:[^\n]+\n?)+)/g))
        for (const n of m[1].matchAll(/-[ \t]+name:[ \t]*["']?([^\s"']+)/g)) s.creds.add(n[1]);
      // storage used
      for (const m of d.matchAll(/claimName:[ \t]*["']?([^\s"']+)/g)) if (!/__\w+__/.test(m[1])) s.storage.add(m[1]);
      continue;
    }
    if (kind === "PersistentVolumeClaim") { S(service).declaredPvc.add(metaName(d) ?? "?"); continue; }
    if (kind === "Ingress") {
      const s = S(service);
      for (const m of d.matchAll(/[ \t]+host:[ \t]*["']?([^\s"']+)/g)) s.ingress.add(m[1]);
      continue;
    }
  }
  // in-cluster service calls (any *.<ns>.svc[.cluster.local] in the file) → cross-service edge
  const s = S(service);
  for (const m of text.matchAll(/\b([a-z0-9-]+)\.([a-z0-9-]+)\.svc(?:\.cluster\.local)?\b/g)) {
    if (m[2] !== service) s.calls.add(`${m[2]}`); // called namespace
  }
}
svc.delete("flux-system"); // the Flux control plane isn't a domain service; its DAG is rendered separately

// ---- stats ----
const nSvc = svc.size;
const nWl = [...svc.values()].reduce((n, s) => n + s.workloads.length, 0);
const nPriv = [...svc.values()].filter((s) => s.privateImages.size).length;
process.stderr.write(`[gen-domain-map] services=${nSvc} workloads=${nWl} private-image-services=${nPriv} flux-kustomizations=${flux.size}\n`);

// ---- Flux dependsOn DAG (mermaid) ----
const sid = (s) => "k" + [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7).toString(36);
function depsMermaid() {
  const out = ["```mermaid", "graph LR"];
  const seen = new Set();
  const node = (name) => {
    const id = sid(name); if (seen.has(id)) return id; seen.add(id);
    const dir = flux.get(name)?.dir;
    out.push(`  ${id}["${name}${dir && dir !== name ? `<br/>(${dir})` : ""}"]`);
    return id;
  };
  for (const [name, { dependsOn }] of [...flux].sort(([a], [b]) => a.localeCompare(b))) {
    const to = node(name);
    for (const dep of dependsOn) out.push(`  ${node(dep)} --> ${to}`); // dependency deploys BEFORE dependent
  }
  out.push("```");
  return out.join("\n");
}

// ---- per-service node index ----
function shortImg(i) { return i.replace(/^(docker\.io\/|library\/)/, ""); }
function fluxFor(service) {
  return [...flux].filter(([, v]) => v.dir === service);
}
function nodeIndex() {
  const out = [];
  for (const service of [...svc.keys()].sort()) {
    const s = svc.get(service);
    const ks = fluxFor(service);
    const deps = [...new Set(ks.flatMap(([, v]) => v.dependsOn))];
    let head = `### ${service}`;
    if (ks.length) head += `  ·  Flux: ${ks.map(([n]) => `\`${n}\``).join(", ")}${deps.length ? ` (after: ${deps.map((d) => `\`${d}\``).join(", ")})` : ""}`;
    out.push(head);
    for (const w of s.workloads.sort((a, b) => (a.kind + a.name).localeCompare(b.kind + b.name))) {
      const imgs = w.images.map((i) => PRIVATE_RE.test(i) ? `\`${shortImg(i)}\` 🔒priv` : `\`${shortImg(i)}\``).join(", ");
      out.push(`- **${w.kind}/${w.name}** — ${imgs || "_no image_"}`);
    }
    const line = (label, set, xf = (x) => `\`${x}\``) => {
      if (set.size) out.push(`  - ${label}: ${[...set].sort().map(xf).join(", ")}`);
    };
    line("creds", s.creds, (c) => `\`${c}\``);
    if (s.creds.size) out[out.length - 1] += "  _(→ secrets-map.md)_";
    line("storage", s.storage);
    if (s.privateImages.size) out.push(`  - ⚠️ private image → needs \`ghcr-pull-secret\` (reuse \`ghcr-read-token\`)`);
    line("ingress", s.ingress);
    line("calls", s.calls, (n) => `→ \`${n}\``);
    out.push("");
  }
  return out.join("\n").trimEnd();
}

// ---- output ----
if (flag("--json")) {
  const out = {
    services: Object.fromEntries([...svc].map(([k, s]) => [k, {
      workloads: s.workloads, images: [...s.images], privateImages: [...s.privateImages],
      creds: [...s.creds].sort(), storage: [...s.storage].sort(),
      ingress: [...s.ingress].sort(), calls: [...s.calls].sort(),
      flux: fluxFor(k).map(([n, v]) => ({ name: n, dependsOn: v.dependsOn })),
    }])),
    flux: Object.fromEntries(flux),
    stats: { services: nSvc, workloads: nWl, privateImageServices: nPriv, fluxKustomizations: flux.size },
  };
  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
} else if (flag("--deps")) {
  process.stdout.write(depsMermaid() + "\n");
} else if (flag("--inject") || flag("--check")) {
  const target = flag("--inject") || flag("--check");
  const BEGIN = "<!-- BEGIN GENERATED:domain-map -->";
  const END = "<!-- END GENERATED:domain-map -->";
  const block = [
    BEGIN,
    "<!-- Regenerate: node scripts/gen-domain-map.mjs clusters/pi-k3s --inject docs/domain-map.md -->",
    "<!-- Do not hand-edit between these markers; edits are overwritten. -->",
    "",
    `_${nSvc} services · ${nWl} workloads · ${flux.size} Flux Kustomizations · ${nPriv} services on a private image. Auto-derived from \`clusters/pi-k3s/**\`._`,
    "",
    "## Deploy-order DAG (Flux `dependsOn`)",
    "",
    "_What must reconcile before what. An arrow A → B means A deploys before B._",
    "",
    depsMermaid(),
    "",
    "## Services",
    "",
    "_Per service: what it runs (🔒priv = private image), needs (creds → `secrets-map.md`, storage), how it's reached (ingress), and who it talks to (calls)._",
    "",
    "_Images are listed **without tags** on purpose — this map is topology, and the deployed version is a property of the cluster, not of this repo. Read the live tag with `get_flux_status` / `describe_resource`. (Tags here made every bot image bump a map change, and image-automation pushes bypass the PR gate that regenerates it, so unrelated PRs inherited a red `drift`.)_",
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
      process.stderr.write(`[gen-domain-map] DRIFT: ${target} is stale.\n` +
        `  Run: node scripts/gen-domain-map.mjs clusters/pi-k3s --inject ${target}\n`);
      process.exit(1);
    }
    process.stderr.write(`[gen-domain-map] ok: ${target} up to date\n`);
  } else {
    writeFileSync(target, next);
    process.stderr.write(`[gen-domain-map] injected block into ${target}\n`);
  }
} else {
  process.stdout.write(nodeIndex() + "\n");
}
