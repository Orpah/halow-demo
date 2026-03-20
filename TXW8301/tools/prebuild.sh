#!/bin/bash
echo "Running prebuild script..."
rm -f Obj/common_common.o
# Run precompile to generate __rt_entry.S
echo "Running precompile..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/precompile.sh" "$@"
