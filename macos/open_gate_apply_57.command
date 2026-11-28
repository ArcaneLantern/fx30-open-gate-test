#!/bin/bash
# FX30 (firmware 6.01): 5.7K, NOT RUN ON ANY FX30: a real 5760x3840 file of the same 5952x3968 sensor window, in XAVC S 4K at 24p (25p on PAL), about 300 Mbps on the 100M record settings, I and P pictures only (no B frames), MP4 headers at 5760x3840 (four steps from a cold boot, then one read-only session).
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --57 "$@"
