"""Hook entry point: run `orch.py` as an imported module so its bytecode is cached.

Python never caches bytecode for a script run directly, so `python3 orch.py` recompiles the
whole file on every hook fire (~35 ms). Importing it lets the interpreter reuse the cached
`.pyc`. Behaviour is otherwise identical to `orch.py <args>`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orch  # noqa: E402

if __name__ == "__main__":
    sys.exit(orch.main(sys.argv[1:]))
