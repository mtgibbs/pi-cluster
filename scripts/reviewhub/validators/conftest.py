"""pytest path setup for validator unit tests.

Puts the validators dir (so `import <name>`) and scripts/ (so `import
triggerable_judge`) on sys.path — mirrors the insertion __init__.py does at
import time. Lets each test_<name>.py just `from <name> import ...`.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parents[1])):  # validators dir, then scripts/
    if _p not in sys.path:
        sys.path.insert(0, _p)
