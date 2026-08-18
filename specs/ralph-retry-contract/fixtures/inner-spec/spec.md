# Spec: inner fixture — a two-check gate for exercising the retry contract

Not a real feature. `verify.sh` passes only when BOTH `a.txt` and `b.txt` exist, so a mock
executor can make one check pass while regressing the other.
