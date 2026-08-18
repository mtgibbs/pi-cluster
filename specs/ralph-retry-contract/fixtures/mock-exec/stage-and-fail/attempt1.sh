# Write a file AND stage it, then leave the gate failing. This is what qwen-61568 did.
echo 'attempt-1 work' > "$ROOT/staged.txt"
git -C "$ROOT" add staged.txt
