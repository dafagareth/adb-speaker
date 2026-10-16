#!/bin/sh
# Project: adb-speaker
# File: smoke.sh (Linux Packaging)
# Description: Verifies portable Linux archive execution inside a clean container.
#
# Copyright (c) 2026 dafagareth
# SPDX-License-Identifier: MIT
# Licensed under the MIT License (see LICENSE in repository root).
# https://opensource.org/licenses/MIT
set -eu
package_test_dir=$(mktemp -d)
trap 'rm -rf "$package_test_dir"' EXIT HUP INT TERM
tar -xzf dist/adb-speaker-linux-x86_64.tar.gz -C "$package_test_dir"
# A plain image catches libraries that happen to be installed on the build host.
docker run --rm --network none \
    -v "$package_test_dir/adb-speaker:/app:ro" ubuntu:22.04 /bin/sh -ec '
    test ! -x /usr/bin/python3
    test ! -x /usr/bin/adb
    test ! -x /usr/bin/parec
    PATH=/nonexistent /app/adb-speaker --help >/dev/null
    export LD_LIBRARY_PATH=/app/_internal
    /app/_internal/bin/adb version
    /app/_internal/bin/parec --version
'
