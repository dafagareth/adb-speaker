"""
Project: adb-speaker
Module: __init__.py
Description: Package entry point and public API re-exports for adb-speaker.

Copyright (c) 2026 dafagareth
SPDX-License-Identifier: MIT
Licensed under the MIT License (see LICENSE in repository root).
https://opensource.org/licenses/MIT
"""

__version__ = "0.2.0"

from .cli import run

__all__ = ["__version__", "run"]
