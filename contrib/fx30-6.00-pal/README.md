# FX30 6.00 PAL — 50p open-gate step (contribution)

This folder is a **6.00-only** addition to the kit, offered as a branch/PR. It does not change any existing step.
Tested on: ILME-FX30, firmware **6.00**, PAL, USB identity **2 same / 5 differ** (the build `check_readonly` calls NOT READY).

## Why a separate step

The kit's designs are addressed for **6.01** libmpr (`2ba4e927…`, 3,517,008 B). This body has **6.00** libmpr
(`8f37bc75…`, 3,500,624 B). Sensor, output-size and screen steps have identical addresses on both and run unchanged.
The encoder step (L19) refuses on 6.00 (`not as in the file`), so the 50p encoder design is **relinked** here:
`mp_lm` sites moved **−0x19b8** (MP4 height code) and **−0x3d00** (`g_videoParamComb`).

The second problem the 50p step fixes: the kit's HS design patches 29 descriptors, all 23.98p/25p, and **PAL XAVC HS 4K is
50p only**. The stream therefore stayed at height 2160 against a 2560-row picture and the camera restarted when record
opened the HEVC channel (issue #10). The contributed **p50 group** (height 2560, `UseCore=2`, level 6.0) is included in
`expected_mp_ogfile50p_fx30_relink.h`.

## Files

| File | Level | SHA-256 | What |
|---|---|---|---|
| `libJit_fx30_L19_50p_relink.so` | N102 | `b6d009db18aa61a7b03fb91cbd0433840bd65acf8325fc77096d94c9a99251a2` | apply the 50p encoder design at 6.00 addresses (**use this one**) |
| `libJit_fx30_L20_50p_relink.so` | N103 | `569b756907b6a6a228391977afc1d0cddc5260cce9855e0f86f0053050a183d4` | put it back |
| `libJit_fx30_L5_50p_sensor.so` | N99 | `388f14e1af244d0d3681f890ab4c7f6389d25b551019c9651cfd460d5effb5e6` | optional fallback: 50p sensor step for mode 0x830 (smaller 5612×3732 window) |
| `libJit_fx30_L6_50p_sensor.so` | N96 | `98996e2efe708f2b9b6ff266f695bb6032c6631a4542ce01c9a817eb3217db4a` | put the fallback back |
| `expected_mp_ogfile50p_fx30_relink.h` | — | `4a98507aa1b41ca7…` | generated site/stock table for N102 (6.00 relink) |
| `expected_sites_ogsq50_fx30_v1.h` | — | `cdd5f96ca1a8f938…` | site table for the optional sensor step |
| `D-50p-rec-830.json` | — | `a25c9b9a9b3ef0fe…` | the 0x830 record used by the sensor fallback |
| `fx30_run.steps.diff` | — | — | the `WRITE_STEPS` additions we used (for reference) |

All libraries are freestanding AArch64, built with ziglang 0.16.0, no imports. They are **not** PIN-verified by the
kit author; the hashes above are ours. Nothing here writes to flash: all payloads are RAM-only and a battery pull
restores stock.

## Order and result

Apply **N102 first** (its guard requires `lm 0x21ff60` to be stock), then the normal open-gate steps:

```text
N102 -> L5 -> L16 -> N97
```

Do **not** apply the old N98 before N102; N102 covers all 101 av-cam sites N98 covered.

Measured on the body above, one session, four clips (details and the full "Please send back" list in
[issue #13](https://github.com/ArcaneLantern/fx30-open-gate-test/issues/13)):

| Format | Size | fps | Duration | Frames | Result |
|---|---|---|---|---|---|
| XAVC S 4K 25p | 3840×2560 | 25.000 | 79.20 s | 1,980 | no drops, no band |
| XAVC S 4K 50p | 3840×2560 | 50.000 | 169.44 s | 8,472 | no drops, no band |
| XAVC HS 4K 50p | 3840×2560 | 50.000 | 194.40 s | 9,720 | no drops |
| XAVC HS 4K 50p | 3840×2560 | 50.000 | **706.08 s** | **35,304** | no drops, no thermal stop |

`cropdetect` on all four: `3840:2560:0:0`. FOV (25p vs 50p, AVC and HS): best scale **1.0000** — no crop.
The full 3968-row sensor window works at 50p on this body, so the optional N99/N96 fallback was **not** needed.

## Caveats

- 6.00 only. On 6.01 the kit's own L19 step is the right one; these libraries will refuse (guard).
- The 5 identity differences are the 6.00/6.01 version gap, not a relink. A NOT READY verdict does not mean the kit
  cannot work.
- `*M01.XML` still says 3840×2160 / 16:9 (MP4 `tkhd` is correct). Separate writer table, not fixed here.
- In-camera playback was not tested (the kit's own warning).
