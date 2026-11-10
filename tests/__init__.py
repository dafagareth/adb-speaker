"""Add the checkout's src/ directory to sys.path if it is missing.
This runs when tests are imported through the tests package.
"""

# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
