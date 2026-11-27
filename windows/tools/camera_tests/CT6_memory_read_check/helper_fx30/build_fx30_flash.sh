#!/bin/bash
# Build the FX30 6.01 external-flash step (session HS1, 2026-11-27): fx30flash.c with the header of gen_fx30_flash.py.
# usage: build_fx30_flash.sh        (writes libJit_fx30_F18.so, F19, F20 into this folder and prints SHA-256, size, step)
#   F18 read-only check, F19 apply, F20 put back (design fx30flash_v2, modding/FX30_FLASH_ENABLE.md).
# Same pinned flags as helper/rebuild.sh and build_fx30.sh; no library to link against (the step has no imports).
set -e
H="$(cd "$(dirname "$0")" && pwd)"
cd "$H"
for L in 18 19 20; do
  ../../../work/venv_zig/Scripts/python.exe -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror -fPIC -shared -nostdlib -ffreestanding \
    -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096 \
    -DLEVEL=$L fx30flash.c -o "libJit_fx30_F$L.so"
done
for N in F18 F19 F20; do echo "$(sha256sum libJit_fx30_$N.so | cut -d' ' -f1) $(stat -c %s libJit_fx30_$N.so) $N"; done
