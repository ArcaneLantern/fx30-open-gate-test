#!/bin/bash
# FX30 (firmware 6.01): A/B TEST: apply the open-gate state with the sensor step's VARIANT B (two values differ: first phase-detect row 145, read-out length 2020). Use it only if the default apply gives a full picture with wrong colour.
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply apply --variant-b "$@"
