# FX30 6.01 port notes

Everything here was read from the FX30 6.01 firmware update (`BODYDATA.DAT`, SHA-256 `33f287f3…28f9`, from Sony's support site) and checked in emulation. **Nothing has run on an FX30.** The working references are the open-gate states that record on the A7 IV (sensor method), the A7S III and the FX3 (kit shape, encoder, screen).

## Which body the FX30 is like

- **Image processor (`cpapp-b.bin`):** the A7 IV's family for everything the open gate touches.
  - The drive-parameter table map has the A7 IV's layout: the constructor caller `0x8e7826` equals the A7 IV's `0x89a07e`.
  - The picture records have the A7 IV's layout, and its packers rebuild every stock FX30 pair exactly.
  - The resize calculation is the A7 IV's code: entry `0xa8c274` = `0xa2cabc`.
  - What differs: its own 31 drive modes, a 14-column register matrix and 14-byte read-out rows.
- **Main processor (`av-cam.bin`, `libmpr.so`, `appFw.so`):** the FX3's, moved.
  - The encoder tables, MP4 writer and playback decoder are the FX3's (av-cam shift +0xee1c).
  - The display code is the FX3's (`+0x3890`, the 2.0x crop `+0x68bd6`).

## Sensor side: `ogsq_fx30_v1` (step L5)

**What the FX30 does in 4K 16:9** (all asserted by `build/build_og_fx30.py`):

- **Modes.** Drive modes `0x820, 0x880, 0x890, 0x8c0, 0x8d0` (indices 2, 4, 5, 6, 7 of the sorted id table `0xd10d68`) read the same 5952 × 3348 window from row 406. Their crop, stream-0, stream-1, LC and read-out rows are equal, and they use register-matrix column 1 (column map `0x1039938`).
- **Timing** (1/36 MHz units):

  | Mode | 60 Hz table | 50 Hz table |
  |---|---|---|
  | `0x8c0` | 340 × 4410 = 23.976p | 24.000p |
  | `0x820` / `0x880` | 29.97p | 25p |
  | `0x890` / `0x8d0` | the same rates at line length 360 | |

- **Records.** The record selector `0x73ccde` gives all five modes the same picture-record pair `0xc79440` / `0xc79ff8` (frame 5976 × 3356, crop 5952 × 3348, first stage 4336 × 2438).
- **The window is not in the register matrix** (`0x1038e48`, 139 rows of 20 bytes). Columns 1 (5952 × 3348), 2 (5612 × 3156), 8 (4648 × 2616) and 9 (5952 × 3140) are byte-identical. The window comes from the per-mode tables, through the stored drive-parameter record that the calculator `0x354204` computes from them at start-up.

**The design.** A 5952 × 3968 (3:2) window from row 96, centred where the 16:9 one is (row 2080), keeping column 1 and the 4K line timing:

| Table (row size) | Field | Stock → design | Rule it follows (all FX30 movie modes) |
|---|---|---|---|
| geometry `0xcb57a8..` (12, by mode id) | +10 window row | 406 → 96 | = crop row |
| crop `0xd10de4` (20) | +6 window row | 406 → 96 | |
| crop | +18 first phase-detect block k | 9 → 2 | LC +12 = 25 + 48 k |
| stream-0 `0xe0278a` (38) | +26 window height | 3348 → 3968 | |
| stream-1 `0xe02c24` (38) | +26 phase-detect rows p | 68 → 82 | blocks at rows 25 + 48 j inside the window's margins |
| LC `0xe030be` (14) | +8 window row, +12 first phase-detect row | 406 → 96, 457 → 121 | |
| read-out `0xe03270` (14) | +4 f2 (line pairs ahead of the picture) | 41 → 48 | 2 f2 = p + 14 at line 340 |
| read-out | +12 read-out length (line periods) | 1704 → 2014 | (rows + 12) / 2 + 24 |

- Row 96 puts the first and last phase-detect block well inside every margin the four stock movie windows allow (blocks j = 2..83).
- **Read-out.** The read-out (2,014 line periods) fits a 24p frame (4,410) and a 30p one (3,528) with room. The rows end at 4,070, below 4,096.
- **Picture records** (`0xc79440` / `0xc79ff8`):
  - first stage 5976 × 3976, crop 5952 × 3968, squeezed by the first scaler into the stock 4336 × 2438 front end (vertical step 6667/4096 = 1.63);
  - 166 fields per record differ from stock;
  - after the first scaler, nothing differs from stock.
- **Row model.** Fitted on the FX30's three stock pairs of this family (3356, 3148 and 3164 rows). Each field that follows the stage rows does so as +rows, +rows/2, +rows/4, +p or +2 f2; `+0x95e` is the window row.
  - Columns, padding and every register word come from the A7 IV's planner and packers (`build_fhnative.assemble`), which rebuild every stock FX30 pair exactly.
  - **Self-test:** the 3356-row pair rebuilt from the 3148-row DCI pair, and the other way round, byte for byte. The only exception is `+0x5ac`, which follows the output shape (4096 in every 16:9-output stock pair) and stays stock.
  - The design pair passes every rule of `build/lint_split_record.py`.
- **Stored records** (RAM, records base `0x20d93a4` + index × 0x160). They come from the FX30's own calculator run with the cells (`build/emu_drvparam.py fx30_601`), 24 bytes per mode:
  - window height `+0x66`, phase-detect rows `+0x8c`, window row `+0xf6` / `+0x102`, first block `+0x10e`, read-out length `+0x142`, first phase-detect row `+0x15a`;
  - the time values derived from them `+0xbc`, `+0xea..+0xf0`, `+0x150`, `+0x154`;
  - the vertical sampling ratio 27/32 at `+6` / `+7` (5952 × 3968 × 27/32 = 5952 × 3348 = 16:9: the A7 IV's ogsq_v3 lever).
  - The time values differ slightly between the 60 Hz and 50 Hz tables, so each record carries an NTSC and a PAL variant. The write level picks the variant all five records hold.
- **Resize lever.** The FX30's own resize code was run with the A7 IV's camera-matched settings (`build/emu_rc_fit_fx30.py`):

  | Window | Ratio | Second scaler takes |
  |---|---|---|
  | stock 5952 × 3348 | | all 2438 rows |
  | 5952 × 3968 | 1/1 | 2057 rows from row 190: the 16:9 cut the A7 IV showed without the ratio |
  | 5952 × 3968 | 27/32 | **all 2438 rows from row 0** |

## Raw write buffer: no step

Memory id `0x43e` (key `0x57f`) is 24,676,096 bytes. The raw port allows rows × pitch, and the pitch is 6016 = 3008 + 3008, the sum of the halves' frame widths, as on the A7 IV:

- 3976 rows need 23,919,616 bytes, which fits;
- the largest that fits is 4,101 rows.

The FX30's own allocator code was run in emulation (`modding/FX30_PORT_DMM_SIZE.md` in the map).

## Output size: `outsz2560_fx30_v1` (step L16)

- **Size table** at `0x155d40c`: base `0x155d3bc`, set up by `0x4644bc` (the A7 IV's `0x4293c8`). Its 16 entries equal the A7 IV's.
- **Reader** `0x480a36`, case 3, loads base + 0x88.
- **Site** `0x155d444`: 3840 × 2160 → 3840 × 2560. Guards: `0x155d43c`, `0x155d448`.
- **Output buffer:** id `0x2d9` (9 × 13,271,040 bytes) holds 3840 × 2560 at format code 2.

## Encoder and MP4 headers: `ogfile2560_hs_s_fx30_v2` (L19), `_v1` (N19)

The FX3 kit's designs site for site at the FX30's addresses: the same 29 descriptors and profiles, 101 av-cam sites and 4 libmpr sites, plus the two MP4 header heights.

| What | Address |
|---|---|
| descriptors (689) | `0x392758` |
| unit types | `0x3926b8` |
| clip table | `0x39061c` |
| libmpr `g_videoParamComb` | `0x2cb138` |
| MP4 height code sites | `0x21ff68` (AVC), `0x2200a0` (HEVC): `mov w6, #0x870` → `#0xa00` |

Emulated on the FX30's own code:

- **MP4 writer** (track config `0x21fef0`, `stsd` `0x221490`, PROF `0x22313c`): 416 requests; v2 gives 3840 × 2560 in every accepted request.
- **Matcher** `0x224490` and the memory and start-block builders: all checks pass for v1 and v2.

## Rear screen and De-Squeeze Display: `lcd32dsq_fx30_v1` (S16)

The FX3 kit's design moved, 30 words and 32 guards (`modding/FX30_PORT_SCREEN.md`):

| Part | Address | Change |
|---|---|---|
| 16:9 letterbox ratio | `0x1e3048` | 9/16 → 2/3 |
| frame tables (16:9 entries) | `0xde78dc`, `0xde7954`, `0xde79cc` | as the FX3's |
| de-squeeze ratios | `0x1e2f38..`, `0x1e2f90..` | 1.3x 20/39, 1.5x 4/9, 1.6x 40/99, 2.0x 1/3 |
| 2.0x centre crop | `0x663b0c`, `0x663b3e` | off |

- **Panel-type bytes:** rear `0x16295d4`, second output `0x1629704`. Expected 4:3 (2,359,296 dots = 1024 × 768), not read yet.
- **Checks:** Unicorn 32 cases, qemu-arm 156 cases.

## Playback step (optional): `avdec8k_fx30_v1` (P29 / P30)

As on the FX3, create-ch `0x21738c` always opens row 0 (4096 × 2160) with the 4K ids `0x47d` / `0x47f`, so 3840 × 2560 clips are expected not to play.

- **The step:**
  - code words `0x21717c`, `0x217188`, `0x2171f8`, `0x217204` → `0x47c` / `0x47e`;
  - data `0xbf6570` → 7690 × 4320;
  - code page `0x217000`, offset 0x17000 from a 2 MB boundary.
- **Emulation:** 35 cases (`emu_fx30_playback.py`).
- **Not run on any camera;** the FX3's own was not run either.

## The helper and its checks

- **Read-only** `fx30read_v1` (`helper_fx30/fx30read.c` = the FX2/FX3 helper with text changes):
  - identity: three libraries and four coprocessor code pages (`0x128000`, `0x73c000`, `0x464000`, `0x8e7000`);
  - 46 coprocessor sites (8 sensor, 5 stored records, output size, 30 screen words), 6 libmpr and 101 av-cam sites;
  - the dump adds 13 page ranges: register shadow `0x1123000`, matrix, records, size table, the image processor's kprint and boot logs, the resize module `0x1571000` / `0x12dd000`, the panel page and the display pages.
  - **Emulation (`emu_fx30.py`): 24 cases pass**, including a PAL camera, the FX3, FX2 and A7 IV refused, and the FX3, FX2, ZV-E1 and A7S III kits' checks saying NOT READY on an FX30.
- **Write levels** (`helper/readcheck.c`):
  - L5/L6 use a new `MULTI_REC` path: five stored records, each in two timing variants. Sensor object `0x13bd0d8` → control → `+0x690` → drive-parameter object. The control object's constructor stores it there, as the A7 IV's stores `+0x684`.
  - Builds without the switch are unchanged: the preprocessed source of every kit's level 5/6 configuration is identical (138 configurations).
  - **Emulation (`emu_fx30_write.py`): 87 cases pass:**
    - NTSC and PAL apply / again / put back;
    - a mixed NTSC/PAL camera refused, a foreign window refused;
    - lost writes undone, broken pointer chains refused;
    - every guard of L16 and S16, the encoder with and without the header heights, the playback step;
    - the FX3, FX2, A7C II and A7 IV kits' libraries writing nothing on an FX30.

## Not known until an FX30 runs it

- Whether the sensor and its link take the 3968-row window at the 4K line rate. No stock movie mode reads more than 3,348 rows; the stills modes read 4,128 at a slower line.
- Whether the phase-detect row count (82) and the read-out field f2 (48) are what the sensor sends. The rules hold on every stock movie window but were derived, not traced to the sensor driver.
- The second scaler's result on the camera (its block address is predicted only; the dump searches for known sizes).
- What `0x890` / `0x8d0` are used for (the same windows at line length 360: probably the high base ISO). Both are patched.
- The power switch, the panel type, exposure and autofocus, rolling shutter and heat, HDMI, the playback step, 30p and PAL 24.00p (patched on the picture side, not on the encoder side: do not record them).
