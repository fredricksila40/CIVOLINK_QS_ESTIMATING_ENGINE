"""Package entry point (Phase 21): ``python -m qs_engine``.

Delegates to the mode launcher (default: desktop UI). Existing
launchers (run_app.py, qs_engine.cli) are untouched.
"""

import sys

from qs_engine.main import main

if __name__ == "__main__":
    sys.exit(main())
