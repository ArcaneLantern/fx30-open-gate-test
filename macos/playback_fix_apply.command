#!/bin/bash
# FX30 (firmware 6.01): OPTIONAL, NOT RUN ON ANY CAMERA: in-camera playback of 3840x2560 clips with the A7 IV's decode channel (changes 4 instructions and 1 table word of av-cam.bin; refuses unless the caches can be made to fetch them).
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply playback "$@"
