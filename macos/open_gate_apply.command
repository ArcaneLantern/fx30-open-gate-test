#!/bin/bash
# FX30 (firmware 6.01): apply the open-gate state: a 3840x2560 file of the 5952x3968 (3:2) sensor window in XAVC HS 4K and XAVC S 4K (24p, 25p on PAL), MP4 headers at 3840x2560, and the rear screen at 3:2 with De-Squeeze Display set for it (four steps, then one read-only session). NOT YET RUN ON AN FX30.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply "$@"
