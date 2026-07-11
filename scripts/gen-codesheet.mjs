#!/usr/bin/env -S node --no-warnings
// gen-codesheet.mjs — emit the navigation sheet a qwen session should carry,
// choosing layers by what the target repo actually contains. This is the
// production wrapper over the token-bench generators; the numbers behind every
// choice are in docs/research/codemap-serena-token-efficiency.md (783 trials).
//
//   node gen-codesheet.mjs [root] [--budget 2000]     # sheet text on stdout
//
// Layer selection (measured, not configured):
//   map      always                      (locates files; ~free via prefix cache)
//   symbols  if the repo has real code   (symbol/component graph — arm S)
//   edges    if manifests have refs      (reference graph — arm G)
//   both     -> edges drop code imports  (domain-disjoint — arm GS; two
//            vocabularies for the same relations made the model fabricate
//            sheet lines: site ms3 0/3)
// Output is deterministic for a given tree, so identical bytes across runs
// prefix-cache on the Beelink — regeneration is cheaper than cache files.
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BENCH = join(HERE, "token-bench");
const args = process.argv.slice(2);
const root = args.find((a) => !a.startsWith("--")) ?? process.cwd();
const bIdx = args.indexOf("--budget");
const BUDGET = bIdx >= 0 ? args[bIdx + 1] : "2000";

const gen = (script, extra = []) =>
  execFileSync("node", [join(BENCH, script), root, ...extra], {
    encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
  }).trim();

const map = gen("gen-repomap.mjs", ["--budget", BUDGET]);

// symbols are "real" when at least a few files carry actual edges/exports —
// pi-cluster (pure YAML composition) emits bare paths and stays out.
const symbols = gen("gen-symbols.mjs");
const symbolLines = symbols.split("\n").filter((l) => /::\s+\S/.test(l)).length;
const hasSymbols = symbolLines >= 3;

const edges = gen("gen-edges.mjs", hasSymbols ? ["--no-code-imports"] : []);
const hasEdges = edges.length > 0;

// Block wording matches scripts/token-bench/run-bench.mjs verbatim — this is
// the exact prompt shape the benchmark measured.
const parts = [
  "Below is a compact map of this repository. Use it to open the right files directly " +
  "instead of searching broadly.\n<repo-map>\n" + map + "\n</repo-map>",
];
if (hasEdges)
  parts.push(
    "Below is a reference index of this repository: for each file, the secrets, 1Password items " +
    "(1p:item/field), PVCs, in-cluster services, Flux dependencies, image policies, NFS paths, and " +
    "backup targets it references. Use it to follow cross-file chains directly instead of opening " +
    "each link in the chain.\n<edge-index>\n" + edges + "\n</edge-index>");
if (hasSymbols)
  parts.push(
    "Below is a symbol-level component graph of this repository. Per file: its exported symbols " +
    "(kind; props types incl. extends), which components it renders (Component<-defining/file), " +
    "context Providers it mounts (provides:), custom hooks it calls (hook<-defining/file), " +
    "non-rendered symbols it uses ({names}<-file), barrel re-exports (reexports:), and internal " +
    "API endpoints it fetches. Use it to follow cross-file chains directly instead of opening " +
    "each link in the chain.\n<symbol-graph>\n" + symbols + "\n</symbol-graph>");

const text = parts.join("\n\n");
const mode = hasSymbols && hasEdges ? "GS" : hasSymbols ? "S" : hasEdges ? "G" : "B";
process.stderr.write(`codesheet: mode ${mode}, ~${Math.ceil(text.length / 4)} tokens ` +
  `(map${hasEdges ? "+edges" : ""}${hasSymbols ? "+symbols" : ""})\n`);
process.stdout.write(text + "\n");
