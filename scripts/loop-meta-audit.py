#!/usr/bin/env python3
"""meta-audit.py — which identifiers does the gate demand that no spec document fixes?

NOT a gate check (yet). Five of ten gate-fix commits this session were the same
mistake: a check grepped for a name the spec only DESCRIBED, or never mentioned, or
actively BANNED, and so failed correct work and steered the executor toward the check
instead of the requirement.

    6c6bbf8  demanded `.send(`  — the spec only described "the send method"
    24bdc1c  demanded a literal ShipClient.ship( the required seam makes unnecessary
    4446bed  demanded `isFinal`  — a symbol from the framework INV-2 BANS
    549ed4e  demanded AVAudioRecorder shapes after the task asked for AVAudioFile
    c1d09da  anchored on a container; 7382adf  anchored on a class that got deleted

Each lesson was written into a commit message and re-made anyway. Prose does not
prevent recurrence; the recurrence is the proof. This measures it.

A gate that greps for `foo` asserts `foo` is part of the contract. If no spec document
mentions it, either the spec is missing a norm or the check invented one — both are a
human's call, not something to discover by failing a good build.

It is a REPORT and not a check because it currently finds ~40 identifiers, and an
always-red check blocks every task (the T14 lesson: a too-wide anchor stops the line).
Drive the list down, then wire it in.

    python3 specs/v1/meta-audit.py [--quiet]
"""
import re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Gate-internal by design: names that exist only to be BANNED, build-log tokens, XML
# filters, shell noise. Each entry claims: this is not part of the product contract.
ALLOW = re.compile(r"""^(
    BUILD|FAILED|DOCTYPE|xmlns|Tests|UITests|XCTAssert|Segment|segments|contentsOf
  | openai|deepgram|assemblyai|cognitiveservices|googleapis|elevenlabs|WHISPER|hisper
  | SFSpeechRecognizer                       # INV-2 bans it; that IS the contract
  | Analytics|logEvent|logUpload|log_upload|remoteLog|uploadLogs|track
  | github_pat_|eyJhbGciOi|XCRemoteSwiftPackageReference|testTarget
  | INFOPLIST_KEY_[A-Za-z]+
  | check|class|requires|satisfies|satisfy|space|write|sheet|protocol|struct|verify
  | capture|session|speech|audio|https|atPath|Intent|secrets|webhook|mtgibbs
  
)$""", re.X)


def main():
    code = "\n".join(l for l in (ROOT / SPEC_DIR / "verify.sh").read_text().splitlines()
                     if not l.lstrip().startswith("#"))
    ids = set()
    for m in re.finditer(r"(?:src_app|src_all|src_all_i|stt_real|kit_tests|named_test)\s+'([^']+)'", code):
        ids.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", m.group(1)))

    corpus = ""
    for f in (f"{SPEC_DIR}/spec.md", "docs/research-brief.md", "specs/constitution.md",
              "docs/design-notes.md", "PRD.md"):
        p = ROOT / f
        if p.exists():
            corpus += p.read_text()

    missing = sorted(t for t in ids if not ALLOW.match(t) and t not in corpus)
    total = len([t for t in ids if not ALLOW.match(t)])
    print(f"meta-audit: {len(ids)} identifiers grepped, {total} contract-relevant, "
          f"{len(missing)} fixed by NO spec document")
    if "--quiet" not in sys.argv:
        for t in missing:
            print(f"  {t}")
    print("\nEach line is either a norm missing from the spec, or a check inventing one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
