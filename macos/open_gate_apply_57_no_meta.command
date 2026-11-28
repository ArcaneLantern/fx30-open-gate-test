#!/bin/bash
# FX30 (firmware 6.01): 5.7K with the encoder step that leaves the MP4 headers at 3840x2160.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --57 --no-meta "$@"
