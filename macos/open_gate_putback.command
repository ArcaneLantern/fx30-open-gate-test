#!/bin/bash
# FX30 (firmware 6.01): put all four steps back to stock (it finds which sensor variant is in memory).
# WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd "$(dirname "$0")" || exit 1
exec "$PWD/run.sh" apply putback "$@"
