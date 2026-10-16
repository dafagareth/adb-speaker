#!/usr/bin/env python3
"""
Project: adb-speaker
Module: speaker.py
Description: Compatibility launcher for existing source checkouts.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from adb_speaker.cli import run

if __name__ == "__main__":
    run()
