#!/bin/bash
# Build the FX30 read-only helper. usage: build_fx30.sh check|dump <out file>
# Same pinned flags as helper/rebuild.sh and helper_s3/build_s3.sh; linked against the FX30 6.01 libsencore.so for its three imports.
set -e
H="$(cd "$(dirname "$0")" && pwd)"
SEN="$H/../../../work/extracted/fx30_601/0700_part_image/dev/nflasha15/lib/libsencore.so"
cd "$H"
case "$1" in
  check) D=0; X=() ;;
  dump) D=1; X=() ;;
  check57) D=0; X=('-DEXPECTED_H="fx30_expected57.h"') ;;      # the 5.7K twin: the 5.7K designs as the targets (gen_fx30.py --57)
  dump57) D=1; X=('-DEXPECTED_H="fx30_expected57.h"') ;;
  *) echo "usage: build_fx30.sh check|dump|check57|dump57 <out>"; exit 2 ;;
esac
../../../work/venv_zig/Scripts/python.exe -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror -fPIC -shared -nostdlib -ffreestanding \
  -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096 \
  -DDUMP=$D "${X[@]}" fx30read.c "$SEN" -o "$2"
echo "$(sha256sum "$2" | cut -d' ' -f1) $(stat -c %s "$2") $1"
