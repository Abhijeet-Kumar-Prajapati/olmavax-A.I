#!/usr/bin/env python3
"""
Open Charvis launcher.

    py charvis.py                 interactive chat
    py charvis.py ui --open       3D interface in your browser
    py charvis.py voice           wake-word listening
    py charvis.py doctor          diagnose the installation
    py charvis.py test            run the test suite

Everything else is available through ``py charvis.py --help``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opencharvis.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())