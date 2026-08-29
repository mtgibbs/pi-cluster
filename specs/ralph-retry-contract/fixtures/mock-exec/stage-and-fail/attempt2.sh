# Record whether attempt 1's STAGED file survived the reset. This file is the AC7 verdict.
if [ -e "$ROOT/staged.txt" ] || git -C "$ROOT" diff --cached --name-only | grep -q staged.txt; then
  echo "DIRTY" > "$MOCK_DIR/verdict"
else
  echo "CLEAN" > "$MOCK_DIR/verdict"
fi
echo 'attempt-2 work' > "$ROOT/other.txt"
