#!/usr/bin/env bash
# Wrapper → kits-two-venv/stop_runtime.sh (see kits-two-venv/README.md#stop_runtimesh).
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kits-two-venv/stop_runtime.sh" "$@"
