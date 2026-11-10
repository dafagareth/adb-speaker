"""Set the package version, then import and export the CLI's run function.
Setuptools reads __version__ when building the package.
"""

# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT

__version__ = "0.2.0"

from .cli import run

__all__ = ["__version__", "run"]
