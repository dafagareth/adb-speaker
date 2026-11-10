#!/usr/bin/env python3
"""Add this checkout's src/ directory to the Python import path, then import cli.run.
Call run() when the file is executed as a script. PyInstaller uses this launcher too.
"""

# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from adb_speaker.cli import run

if __name__ == "__main__":
    run()
