#!/usr/bin/env bash
# submit.sh — start one factory run from an idea, and print the run URL.
#
#   FABRO_URL=... FABRO_DEV_TOKEN=... factory/submit.sh [--target <name>] [--profile <name>] [--panel "<k=v ...>"]
#       [--spec <name>] [--issue <n>] [--gate-mode human|auto] [--create-only] [--dry-run] "<idea text>"
#
# The laptop's entry point. All the logic is in factory/submit.py (shared with the in-cluster
# intake, factory/intake/); run `factory/submit.sh --help` for every flag. From the laptop the
# gate mode is `human` unless you say otherwise: the run stops at `approve_spec` for you.
# auto_approve is always sent as false. Reads FABRO_URL and FABRO_DEV_TOKEN; prints no secret.
set -euo pipefail
exec python3 "$(cd "$(dirname "$0")" && pwd)/submit.py" "$@"
