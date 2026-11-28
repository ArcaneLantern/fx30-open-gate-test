#!/bin/bash
# Build the FX30 6.01 write libraries from the A7 IV helper's source (helper/readcheck.c), with this build's tables and constants
# (FX30 port, 2026-11-26). Run gen_fx30_write.py first.
# usage: build_fx30_write.sh        (writes libJit_fx30_<step>.so into this folder and prints SHA-256, size, step)
# Flags are those of helper/rebuild.sh. Differences from an A7 IV build: the headers of gen_fx30_write.py, the FX30 6.01 libsencore.so to link
# against, and these constants (modding/FX30_PORT.md):
#   L5/L6    IMAGER 0x13bd0d8 (0x8e5838 returns it; = A7 IV 0x8981f2), drive-parameter pointer at control +0x690 (the constructor block
#            0x8e78bc stores it at 0x8e79e2, where the A7 IV's stores +0x684), stored record 0x160 bytes (0x8e8800). The header sets MULTI_REC:
#            five stored records (0x820, 0x880, 0x890, 0x8c0, 0x8d0), each in an NTSC and a PAL variant. Design ogsq_fx30_v2 (v1 left
#            the sensor's window registers, the register matrix's column 1, stock: three cameras, 2026-11-25/26).
#   L19/L20, N19/N20, P29/P30   av-cam.bin at physical 0x401000000 (kemco: memrsv=0x01000000@0x401000000:ex, as the FX3)
# Steps: L = open gate (5/6 sensor side, 16/17 output size, 19/20 encoder side with the MP4 header heights), N19/N20 = the encoder side
# without the heights (--no-meta), S = the rear screen and De-Squeeze Display words (16/17), P = the optional playback decoder (29/30).
# No L13/L14: the FX30's stock raw write buffer unit holds the 3976-row stage (modding/FX30_PORT_DMM_SIZE.md).
set -e
H="$(cd "$(dirname "$0")" && pwd)"
SEN="$H/../../../work/extracted/fx30_601/0700_part_image/dev/nflasha15/lib/libsencore.so"
cd "$H/../helper"
CC=(../../../work/venv_zig/Scripts/python.exe -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror -fPIC -shared -nostdlib -ffreestanding
    -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096)
for L in 5 6; do
  "${CC[@]}" -DLEVEL=$L '-DSITES_H="expected_sites_ogsq_fx30_v2.h"' '-DDESIGN_LABEL="ogsq_fx30_v2"' -DIMAGER=0x13bd0d8UL -DCTRL_DRVPARAM=0x690U -DREC=0x160U \
    readcheck.c "$SEN" -o "$H/libJit_fx30_L$L.so"
done
for L in 5 6; do     # B5/B6: the sensor design's variant B (the LC and read-out values of the repo's issue 1), for an A/B test
  "${CC[@]}" -DLEVEL=$L '-DSITES_H="expected_sites_ogsq_fx30_v2b.h"' '-DDESIGN_LABEL="ogsq_fx30_v2b"' -DIMAGER=0x13bd0d8UL -DCTRL_DRVPARAM=0x690U -DREC=0x160U \
    readcheck.c "$SEN" -o "$H/libJit_fx30_B$L.so"
done
for L in 16 17; do
  "${CC[@]}" -DLEVEL=$L '-DWORDS_H="expected_words_outsz2560_fx30_v1.h"' readcheck.c "$SEN" -o "$H/libJit_fx30_L$L.so"
  "${CC[@]}" -DLEVEL=$L '-DWORDS_H="expected_words_lcd32dsq_fx30_v1.h"' readcheck.c "$SEN" -o "$H/libJit_fx30_S$L.so"
done
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_fx30_v2.h"' -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx30_L$L.so"
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_fx30_v1.h"' -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx30_N$L.so"
done
# 5.7K (2026-11-28): the A7 IV's real 5760x3840 state on the FX30. K5/K6 = og57n_fx30_v1 (ogsq_fx30_v2 with the first-stage picture at
# 5760x3840; the same five stored records, NTSC or PAL); K16/K17 = og57cp_fx30_v1 (four scaler units, the 0x43f output buffer, the output size
# 5760x3840), in L16's place; K19/K20 = ogfile57r300m1_fx30_v4 (two encoder cores, 300 Mbps on the 100M settings, I and P pictures only, the
# HEVC edit list at 0, the MP4 headers at 5760x3840); M19 = ogfile57r300m1_fx30_v3 (the same without the MP4 size: --no-meta; put back by K20).
for L in 5 6; do
  "${CC[@]}" -DLEVEL=$L '-DSITES_H="expected_sites_og57n_fx30_v1.h"' '-DDESIGN_LABEL="og57n_fx30_v1"' -DIMAGER=0x13bd0d8UL -DCTRL_DRVPARAM=0x690U -DREC=0x160U \
    readcheck.c "$SEN" -o "$H/libJit_fx30_K$L.so"
done
for L in 16 17; do
  "${CC[@]}" -DLEVEL=$L '-DWORDS_H="expected_words_og57cp_fx30_v1.h"' readcheck.c "$SEN" -o "$H/libJit_fx30_K$L.so"
done
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_ogfile57r300m1_fx30_v4.h"' -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx30_K$L.so"
done
"${CC[@]}" -DLEVEL=19 '-DMP_H="expected_mp_ogfile57r300m1_fx30_v3.h"' -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx30_M19.so"
for L in 29 30; do
  "${CC[@]}" -DLEVEL=$L '-DAD_H="expected_ad_avdec8k_fx30_v1.h"' -DAVCAM_PHYS=0x401000000UL readcheck.c -o "$H/libJit_fx30_P$L.so"
done
cd "$H"
for N in L5 L6 B5 B6 L16 L17 L19 L20 N19 N20 S16 S17 P29 P30 K5 K6 K16 K17 K19 K20 M19; do echo "$(sha256sum libJit_fx30_$N.so | cut -d' ' -f1) $(stat -c %s libJit_fx30_$N.so) $N"; done
