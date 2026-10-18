#!/usr/bin/env python3
"""
Olmavax Agent launcher.

    py olmavax_agent.py                 interactive chat
    py olmavax_agent.py ui --open       3D interface in your browser
    py olmavax_agent.py voice           wake-word listening
    py olmavax_agent.py doctor          diagnose the installation
    py olmavax_agent.py test            run the test suite

Everything else is available through ``py olmavax_agent.py --help``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from olmavax_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())