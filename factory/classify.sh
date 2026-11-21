#!/usr/bin/env bash
# classify.sh — the factory's risk classifier. Deterministic: same diff in, same class out.
#
#   git diff --no-renames -U1000000 <base> | factory/classify.sh [--tampered "<why>"]
#
# Reads a unified diff on stdin. Use FULL context (-U1000000) so a tool file's whole
# post-image is visible — the readOnly:false / exec rule looks at the file, not just the hunk.
# Prints `class=A|B|C` on the first line, then one `reason:` line per rule that fired
# (the highest class any path hits wins). Exit 0 when classified; exit 2 when the input
# is empty or unparseable — the caller must treat that as "hold", never as class A.
#
# --tampered "<why>": the caller (steps.py) compares specs/<name>/verify.sh with the blob
# it locked at spec approval and passes this when they differ. A tampered gate is class C.
#
# Classes are defined in factory/README.md ("Risk classes"). No model is consulted.
set -euo pipefail

tampered=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tampered) tampered="${2:-unspecified}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "classify.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

diff_file=$(mktemp)
trap 'rm -f "$diff_file"' EXIT
cat > "$diff_file"

if ! grep -q '^diff --git ' "$diff_file"; then
  echo "classify.sh: no 'diff --git' header on stdin — empty or not a git diff" >&2
  exit 2
fi

LC_ALL=C awk -v tampered="$tampered" '
function rank(c) { return c == "C" ? 3 : (c == "B" ? 2 : 1) }
function hit(c, why) {
  if (rank(c) > rank(cls)) cls = c
  if (!(why in seen)) { seen[why] = 1; reasons[++nr] = c ": " why }
}
function is_test(p) {
  return p ~ /(^|\/)__tests__\// || p ~ /\.(test|spec)\.(c|m)?[jt]sx?$/ || p ~ /(^|\/)(test|tests)\//
}
function base(p,   n, a) { n = split(p, a, "/"); return a[n] }
# Path rules — evaluated once per file path (old and new side both count).
function path_rules(p,   b) {
  if (p == "" || p == "/dev/null") return
  b = base(p)
  if (b ~ /^(package\.json|package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml)$/) hit("C", p " — dependency manifest/lockfile")
  if (b ~ /^Dockerfile/ || b == ".dockerignore")                hit("C", p " — container build")
  if (p ~ /^\.github\//)                                         hit("C", p " — CI / GitHub config")
  if (p == ".review-hub.yml")                                    hit("C", p " — review-hub opt-in (judge roster)")
  if (p ~ /^\.fabro\//)                                          hit("C", p " — Fabro config")
  if (b ~ /^\.eslintrc/ || b ~ /^eslint\.config\./ || b == ".eslintignore" || b ~ /^\.prettierrc/) hit("C", p " — lint config")
  if (b ~ /^tsconfig.*\.json$/)                                  hit("C", p " — TypeScript config")
  if (b ~ /^(vitest|vite)\.(config|workspace)\./)                hit("C", p " — test-runner config")
  if (p ~ /^(k8s|deploy|charts)\// || b == "kustomization.yaml") hit("C", p " — deploy / RBAC manifest")
  if (p ~ /^specs\/validators\// || b == "contract.md")          hit("C", p " — judge contract")
  if (p ~ /^src\/(clients|utils)\//)                             hit("B", p " — client/util layer (mutating surface)")
  if (p ~ /^src\// && tolower(p) ~ /auth/ && !is_test(p))        hit("B", p " — auth")
}
function finish_file() {
  if (cur == "") return
  path_rules(oldp); path_rules(newp)
  if (deleted && is_test(oldp))                hit("C", oldp " — test file deleted")
  if (deleted && oldp ~ /^src\/tools\//)       hit("B", oldp " — tool file deleted")
  if (cur ~ /^src\/tools\// && !is_test(cur) && mut_marker != "") hit("B", cur " — tool file " mut_marker)
  if (is_test(cur)) {
    for (t in removed_title) if (!(t in added_title)) hit("C", cur " — test case removed: " t)
  }
  delete removed_title; delete added_title
  cur = ""; oldp = ""; newp = ""; deleted = 0; mut_marker = ""; inhunk = 0
}
function title_of(s,   m) {
  # it("title", ... / test(`title`, ... / it.each(...)("title" -> the first quoted string
  if (match(s, /["\047`][^"\047`]*["\047`]/)) return substr(s, RSTART + 1, RLENGTH - 2)
  return s
}
BEGIN { cls = "A"; nr = 0; nfiles = 0; if (tampered != "") hit("C", "spec verify.sh changed after approval — " tampered) }
/^diff --git / {
  finish_file()
  nfiles++
  # Fallback paths from the header (binary files have no ---/+++ lines).
  hdr = substr($0, 12); i = index(hdr, " b/")
  oldp = substr(hdr, 3, i - 3); newp = substr(hdr, i + 3); cur = newp
  deleted = 0; inhunk = 0; mut_marker = ""
  next
}
!inhunk && /^deleted file mode/ { deleted = 1; next }
!inhunk && /^rename from / { oldp = substr($0, 13); next }
!inhunk && /^rename to /   { newp = substr($0, 11); cur = newp; next }
!inhunk && /^--- /  { p = substr($0, 5); if (p != "/dev/null") { sub(/^a\//, "", p); oldp = p } ; next }
!inhunk && /^\+\+\+ / { p = substr($0, 5); if (p != "/dev/null") { sub(/^b\//, "", p); newp = p; cur = p } else { cur = oldp } ; next }
/^@@ / { inhunk = 1; next }
inhunk {
  tag = substr($0, 1, 1); body = substr($0, 2)
  if (tag != " " && tag != "+" && tag != "-") next
  # Tool files: any line of the file (pre- or post-image) that defines a write or shells out.
  if (cur ~ /^src\/tools\// && mut_marker == "") {
    if (body ~ /readOnly[[:space:]]*:[[:space:]]*false/) mut_marker = "defines a tool with readOnly: false"
    else if (body ~ /execOnNode|child_process|execSync|execFile|spawn\(|(^|[^A-Za-z_.])exec\(|[A-Za-z_.]*Exec\(|node-ssh|NodeSSH|[Ss][Ss][Hh]/) mut_marker = "calls exec/SSH"
  }
  # Any changed line in non-test source that touches the read-only flag or key scope is a gate change.
  if ((tag == "+" || tag == "-") && cur ~ /^src\// && !is_test(cur) && body ~ /readOnly|readonly/) hit("B", cur " — changes read-only flag/scope handling")
  if (is_test(cur)) {
    if (tag == "+" && body ~ /(^|[^A-Za-z_])(it|test|describe|suite)\.(skip|todo|only|fails|skipIf|runIf)([^A-Za-z_]|$)|(^|[^A-Za-z_.])x(it|test|describe)\(/)
      hit("C", cur " — test skipped/focused: " body)
    if (body ~ /^[[:space:]]*(it|test)(\.each[^(]*\([^)]*\))?\(/) {
      t = title_of(body)
      if (tag == "-") removed_title[t] = 1
      else if (tag == "+") added_title[t] = 1
    }
  }
  next
}
END {
  finish_file()
  if (nfiles == 0) { print "classify.sh: no files in diff" > "/dev/stderr"; exit 2 }
  print "class=" cls
  for (i = 1; i <= nr; i++) print "reason: " reasons[i]
  if (nr == 0) print "reason: A: no B/C rule matched (" nfiles " file(s))"
}
' "$diff_file"
