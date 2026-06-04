#!/usr/bin/env bash
# Wrapper → kits-two-venv/cleanup.sh (see kits-two-venv/README.md#cleanupsh).
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kits-two-venv/cleanup.sh" "$@"
