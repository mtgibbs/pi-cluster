# Build whatever task the prompt names. Dispatching on the PROMPT (not an attempt number) is
# what makes this reusable across resumed runs, where invocation order no longer matches task
# order. Each task touches exactly one file and never another task's.
case "$PROMPT" in
  *"T1:"*) echo a > "$ROOT/a.txt" ;;
  *"T2:"*) echo b > "$ROOT/b.txt" ;;
  *"T3:"*) echo c > "$ROOT/c.txt" ;;
esac
