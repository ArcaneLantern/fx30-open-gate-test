#!/bin/bash
# FX30 (firmware 6.01): A/B TEST: change the sensor step back from variant B to the default (two steps, then one read-only session).
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply switch-to-a "$@"
