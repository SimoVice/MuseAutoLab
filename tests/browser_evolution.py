"""Compatibility entry point for the consolidated current source-CAD browser flow.

Specialized CAD/geometry/source/extension assertions also remain in the Python suite.
"""

from pathlib import Path

import browser_smoke as harness
from browser_foundation import run

if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_foundation_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
