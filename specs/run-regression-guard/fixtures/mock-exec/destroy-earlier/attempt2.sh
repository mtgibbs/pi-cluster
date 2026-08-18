rm -f "$ROOT/a.txt"             # T2 attempt 1: DESTROYS T1's work
echo b > "$ROOT/b.txt"          # ...while satisfying its own check
