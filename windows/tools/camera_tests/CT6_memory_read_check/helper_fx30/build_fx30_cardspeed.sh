#!/bin/bash
# Build the FX30 6.01 card-speed step (session MR1, 2026-11-27): fx30cardspeed.c with the header of gen_fx30_cardspeed.py.
# usage: build_fx30_cardspeed.sh        (writes libJit_fx30_V18.so, V19, V20 into this folder and prints SHA-256, size, step)
#   V18 read-only check, V19 apply, V20 put back (design cardspeed_off_fx30_v1, modding/CARD_SPEED_CHECK.md).
# Same pinned flags as build_fx30_flash.sh; no library to link against (the step has no imports).
set -e
H="$(cd "$(dirname "$0")" && pwd)"
cd "$H"
for L in 18 19 20; do
  ../../../work/venv_zig/Scripts/python.exe -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror -fPIC -shared -nostdlib -ffreestanding \
    -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096 \
    -DLEVEL=$L fx30cardspeed.c -o "libJit_fx30_V$L.so"
done
for N in V18 V19 V20; do echo "$(sha256sum libJit_fx30_$N.so | cut -d' ' -f1) $(stat -c %s libJit_fx30_$N.so) $N"; done
