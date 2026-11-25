#!/bin/bash
# FX30 (firmware 6.01): apply the open-gate state with the encoder step without the MP4 header heights: the files' MP4 headers keep saying 3840x2160.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --no-meta "$@"
