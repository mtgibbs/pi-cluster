# Design principles (house style) — taste, encoded

Taste doesn't transfer through a spec or a grep. A literal executor (qwen) builds exactly
what you specify; a static `verify.sh` checks correctness, not whether it *looks* good. This
doc is the reusable **taste layer**: principles every spec inherits, so both the author and
the executor default toward good-looking results — and the human eye at review has less to
catch. Seeded from the homepage refresh (2026-05-23), where 4 functionally-correct-but-ugly
cards passed every automated check and only a human eyeball caught them.

## Dashboards / Homepage

- **One dense card beats many sparse ones.** A single `prometheusmetric` card showing
  VRAM/GPU/Temp/RAM as inline stats > four fat cards each showing one number. Consolidate
  related metrics onto one card.
- **Show live values, not static labels.** "GPU Temp" is noise; "Temp 29°C" is signal.
  Prefer a widget that renders the actual value over a labeled link.
- **Use the purpose-built widget over generic primitives.** `prometheusmetric` for Prometheus
  data, not hand-rolled `customapi` tiles. The named widget exists because someone already
  solved the presentation problem.
- **Distinct, meaningful icons.** Don't reuse one icon for everything (the `mdi-memory` ×3
  smell). One glance should disambiguate the cards.
- **Match the existing surface.** New sections should look like what's already there — the Pi
  node cards set the bar for what a "performance readout" looks like in this lab.

## Choosing a tool / pattern (any domain)

- **Research the idiomatic pattern BEFORE specifying** (Plan-phase design research). The
  question isn't only "what's correct?" but "what's the *conventional, tasteful* way to do this
  in the target system?" Our percent/`customapi` mess came from specifying the first thing that
  worked, not the best-practice thing.

## The boundary (be honest about it)

Static `verify.sh` checks correctness; **taste needs an eye on the rendered artifact.** Always
keep a visual-review step in the loop — a human looking at the page, or (research direction) a
vision model given a screenshot for a first-pass critique ("4 near-empty cards — consolidate?").
Encode as much taste as you can here so that review step catches less, not nothing.
