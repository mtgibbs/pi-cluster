# Spec: inner fixture — two tasks, the second able to destroy the first

Not a real feature. `alpha` is presence-gated on `a.txt` and `beta` on `b.txt`, so removing
`a.txt` makes `alpha` PEND rather than FAIL — reproducing qwen-10668 exactly, and covering the
case a failed-only rule would miss.
