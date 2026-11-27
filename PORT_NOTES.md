# FX30 6.01 port notes

Everything here was read from the FX30 6.01 firmware update (`BODYDATA.DAT`, SHA-256 `33f287f3…28f9`, from Sony's support site) and checked in emulation. The working references are the open-gate states that record on the A7 IV (sensor method), the A7S III and the FX3 (kit shape, encoder, screen).

**Camera runs so far.** Kit v1 ran on three FX30s (2026-11-25/26; one PAL with three dumps, two NTSC in the repo's issues 1 and 2). Kit v2 has not run.

## What the v1 runs showed

- **Worked as built:** the identity check (READY), all four write steps on NTSC and PAL, the PAL variant of the stored records, the MP4 headers (3840 × 2560), the screen step (30 words, 3:2 layout), the closing dump. The rear panel is type 2, **4:3**.
- **Fault:** the picture filled the top 2160 of 2560 rows with normal proportions and black below; colours shifted towards blue and dark levels were crushed.
- **Cause.** The dump's sensor register shadow, taken after the patch in movie mode, still held the stock window:

  | Register | Meaning | Held (stock) | The records said |
  |---|---|---|---|
  | 6 / 7 | first row + 81 | 487 (row 406) | row 96 |
  | 8 / 9 | line pairs | 1680 (3348 rows) | 3968 rows |
  | 14 | first phase-detect block | 9 | 2 |
  | 16 | phase-detect rows / 2 | 34 | 41 |
  | 25 | lead-in line pairs | 41 | 48 |

  These registers come from the register matrix. v1 took the matrix to start at `0x1038e48` (139 rows). It starts at **`0x1038d1c` (154 rows)**: the 15 rows v1 skipped are exactly these. So v1's statement "columns 1, 2, 8 and 9 are identical, the window is not in the matrix" was wrong, and v1 never wrote the sensor's window.
- **How the numbers fit:** 3348 of 3968 rows = 2160 of 2560, and 3348 rows squeezed and stretched by the designed factors keep normal proportions.
- **Also seen under v1:** one camera restarted when File Format was changed to XAVC HS with the patch applied (cause not known); on first entry to MOVIE the screen can show a 16:9 layout until MENU is opened and closed.
- **Harmless lines:** `read failed -21` (ten per write step: directories under `/proc/driver/pcie`) and `truncated at 2048 bytes` (two per dump: a long `/proc` file).

## Which body the FX30 is like

- **Image processor (`cpapp-b.bin`):** the A7 IV's family for everything the open gate touches.
  - The drive-parameter table map has the A7 IV's layout: the constructor caller `0x8e7826` equals the A7 IV's `0x89a07e`.
  - The picture records have the A7 IV's layout, and its packers rebuild every stock FX30 pair exactly.
  - The resize calculation is the A7 IV's code: entry `0xa8c274` = `0xa2cabc`.
  - What differs: its own 31 drive modes, a 14-column register matrix and 14-byte read-out rows.
- **Main processor (`av-cam.bin`, `libmpr.so`, `appFw.so`):** the FX3's, moved.
  - The encoder tables, MP4 writer and playback decoder are the FX3's (av-cam shift +0xee1c).
  - The display code is the FX3's (`+0x3890`, the 2.0x crop `+0x68bd6`).

## Sensor side: `ogsq_fx30_v2` (step L5)

**What the FX30 does in 4K 16:9** (all asserted by `build/build_og_fx30.py`):

- **Modes.** Drive modes `0x820, 0x880, 0x890, 0x8c0, 0x8d0` (indices 2, 4, 5, 6, 7 of the sorted id table `0xd10d68`) read the same 5952 × 3348 window from row 406. Their crop, stream-0, stream-1, LC and read-out rows are equal, and they use register-matrix column 1 (column map `0x1039938`).
- **Timing** (1/36 MHz units):

  | Mode | 60 Hz table | 50 Hz table |
  |---|---|---|
  | `0x8c0` | 340 × 4410 = 23.976p | 24.000p |
  | `0x820` / `0x880` | 29.97p | 25p |
  | `0x890` / `0x8d0` | the same rates at line length 360 | |

- **Records.** The record selector `0x73ccde` gives all five modes the same picture-record pair `0xc79440` / `0xc79ff8` (frame 5976 × 3356, crop 5952 × 3348, first stage 4336 × 2438).
- **The register matrix** `0x1038d1c`: 154 rows of 20 bytes (the address of a register's value in the shadow, 14 column bytes, 2 spare), a zero row, then the column map.
  - The routine `0x8e8218` is the only code that names it: it takes the mode's column from the column map and copies each row's column byte to the shadow (4-byte entries {register, value} from `0x1123de4`).
  - Columns 1 (5952 × 3348), 2 (5612 × 3156), 8 (4648 × 2616) and 9 (5952 × 3140) use the same sensor mode (register 1 = 15) and differ only in seven rows, which follow each mode's own table rows:

    | Register | Rule | Columns 1, 2, 8, 9 |
    |---|---|---|
    | 6 / 7 | window row + 81 | 487, 583, 851, 591 |
    | 8 / 9 | (height + the four margins) / 2 | 1680, 1584, 1316, 1576 |
    | 14 | first phase-detect block (= crop +18) | 9, 11, 16, 11 |
    | 16 | phase-detect rows / 2 | 34, 32, 27, 32 |
    | 25 | read-out f2 (= read-out +4) | 41, 40, 34, 39 |

**The design.** A 5952 × 3968 (3:2) window from row 94, keeping sensor mode 15 and the 4K line timing, written in the sensor's registers and in the tables that describe it:

| Where (row size) | Field | Stock → design | Rule it follows |
|---|---|---|---|
| matrix column 1, registers 6 / 7 | first row + 81 | 487 → 175 | all four columns |
| matrix column 1, registers 8 / 9 | line pairs | 1680 → 1990 | all four columns |
| matrix column 1, registers 14, 16, 25 | first block, phase-detect pairs, f2 | 9 → 2, 34 → 41, 41 → 48 | all four columns |
| geometry `0xcb57a8..` (12, by mode id) | +10 window row | 406 → 94 | = crop row |
| crop `0xd10de4` (20) | +6 window row | 406 → 94 | |
| crop | +18 first phase-detect block k | 9 → 2 | LC +12 = 25 + 48 k in every mode |
| stream-0 `0xe0278a` (38) | +26 window height | 3348 → 3968 | |
| stream-1 `0xe02c24` (38) | +26 phase-detect rows p | 68 → 82 | blocks at rows 25 + 48 j inside the window's margins |
| LC `0xe030be` (14) | +8 window row, +12 first phase-detect row | 406 → 94, 457 → 121 | |
| read-out `0xe03270` (14) | +4 f2 (line pairs ahead of the picture) | 41 → 48 | 2 f2 = p + 14 at line 340 |
| read-out | +12 read-out length (line periods) | 1704 → 2014 | line pairs + 24 |

- **Why row 94.** All four stock windows of this sensor mode start at a row that is 2 modulo 4 (406, 502, 770, 510), and the 4648 × 2616 one sits two rows off the centre 2080 to keep that. Row 94 keeps it (v1 had 96). Its first and last phase-detect blocks lie 33 rows after the outer window's start and 59 before its end; stock shows 31 and 57 as inside (blocks j = 2..83).
- **Checked on the firmware's own routine** (`build/emu_sensor_regs_fx30.py`): `0x8e8218` run for every drive mode, stock and with the design. Stock mode `0x8c0` gives the registers a real camera held after v1 (153 of 154 equal; the other is rewritten while running). With the design, the five modes get 3968 rows from row 94 and no other mode or register changes.
- **Variant B, `ogsq_fx30_v2b` (steps B5 / B6), for an A/B test.** The values suggested in the repo's issue 1: LC +12 = window row + 51 = 145 (v2: 121) and read-out length 2020 (v2: 2014). Stock contradicts "row + 51" as a rule (DCI 510 → 553, Super 35 770 → 793; 145 is off the 48-row grid), so v2 stays the default. But the report of clean colour may come from a state whose sensor was on the tall window, so the values are carried.
  - It differs from v2 in 20 bytes: one byte of the LC row and one of the read-out row in each of the five modes, and two bytes in each stored record (`+0x142`, `+0x15a`). The calculator derives nothing else from them.
  - Sensor registers and picture records are v2's. Each variant's steps write nothing over the other variant (emulated both ways), and the put back finds which one is in memory.
  - The read-only helper reports those sites as TARGET (v2) or TARGET-B; both count as READY.
- **Read-out.** The read-out (2,014 line periods) fits a 24p frame (4,410) and a 30p one (3,528) with room. The window ends at row 4,062, inside the sensor's 4,128.
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

- **Panel-type bytes:** rear `0x16295d4`, second output `0x1629704`. Read on three cameras: rear type 2 = **4:3** (2,359,296 dots = 1024 × 768), second output 0.
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

- **Read-only** `fx30read_v2` (`helper_fx30/fx30read.c` = the FX2/FX3 helper with text changes):
  - identity: three libraries and four coprocessor code pages (`0x128000`, `0x73c000`, `0x464000`, `0x8e7000`);
  - 47 coprocessor sites (9 sensor, one of them the matrix's window rows; 5 stored records, output size, 30 screen words), 6 libmpr and 101 av-cam sites;
  - the dump adds 13 page ranges: register shadow `0x1123000`, matrix, records, size table, the image processor's kprint and boot logs, the resize module `0x1571000` / `0x12dd000`, the panel page and the display pages.
  - **The PC's reading of a dump** (`fx30_run.py`) now decodes the sensor's window registers from the shadow, compares them with the five stored records, and adds a problem line when they disagree.
  - **Emulation (`emu_fx30.py`): 30 cases pass** (with variant B applied: TARGET-B on its seven sites, READY), including a camera in 4K movie mode, a PAL camera, a camera that still holds kit v1 (NOT READY), the FX3, FX2 and A7 IV refused, and the FX3, FX2, ZV-E1 and A7S III kits' checks saying NOT READY on an FX30.
  - **Dump reading (`test_fx30_dump_decode.py`): 14 checks pass** (variant B is read as B on NTSC and PAL): stock in stills and in 4K movie, v2 applied (NTSC and PAL) → sensor and records agree; kit v1's state → they do not, and a problem line says so; the tester's three real v1 dumps give that same reading (those dumps are private and not in the repo, so that part is skipped there).
- **Write levels** (`helper/readcheck.c`):
  - L5/L6 use a new `MULTI_REC` path: five stored records, each in two timing variants. Sensor object `0x13bd0d8` → control → `+0x690` → drive-parameter object. The control object's constructor stores it there, as the A7 IV's stores `+0x684`.
  - Builds without the switch are unchanged: the preprocessed source of every kit's level 5/6 configuration is identical (138 configurations). v2 did not touch `readcheck.c`: only L5, L6, check and dump have new hashes, and B5 / B6 are new.
  - **Emulation (`emu_fx30_write.py`): 113 cases pass:**
    - NTSC and PAL apply / again / put back;
    - the matrix's column 1 holding the new window after L5; a foreign byte there refused; kit v2's L5 and L6 writing nothing on a camera that still holds kit v1;
    - variant B: apply / again / put back on NTSC and PAL; A's steps writing nothing on B and B's on A; both switch orders; a lost write undone;
    - a mixed NTSC/PAL camera refused, a foreign window refused;
    - lost writes undone, broken pointer chains refused;
    - every guard of L16 and S16, the encoder with and without the header heights, the playback step;
    - the FX3, FX2, A7C II and A7 IV kits' libraries writing nothing on an FX30.

## Not known until an FX30 runs v2

- Whether the sensor and its link take 1,990 line pairs from row 94 in this mode. v1 never asked (its registers stayed stock). No stock movie mode reads more than 1,680; the stills modes read the full height at a slower line.
- Whether the colour is right once the sensor and the picture side agree. The v1 fault is explained by the mismatch, but only a camera can confirm it.
- Whether the phase-detect row count (82) and f2 (48) suit the sensor at this height. The rules hold on every stock window of the mode. What reads the stored record's LC and read-out fields (`+0x15a`, `+0x142`) was not traced to its code.
- XAVC HS under the patch (one restart on a format change under v1).
- The second scaler's result on the camera (its block address is predicted only; the dump searches for known sizes).
- What `0x890` / `0x8d0` are used for (the same windows at line length 360: probably the high base ISO). Both are patched.
- The power switch, exposure and autofocus, rolling shutter and heat, HDMI, the playback step, 30p and PAL 24.00p (patched on the picture side, not on the encoder side: do not record them).

## External flash with the electronic shutter: `fx30flash_v2` (F18 / F19 / F20), 2026-11-27, not run

The study behind it, with every finding, is in the map (`reference/hotshoe_flash.md`, `modding/FX30_FLASH_ENABLE.md`). In short:

- **Not stubs.** The FX30's `appFw.so` has the full external-flash code, and so does its coprocessor: the Mi-Shoe controller, the flash request handlers, and a capture-flash scheduler timed from the sensor's exposure. These match the A7 IV's and A1's function for function.
- **Rules.** Two rules sit on the derived key `HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot`. One calls `FUNC_..._electronic_for_haita` (`0xc36`), which forces Flash Mode off; the other calls `..._invalid_for_haita` (`0xc37`) and is used only with pixel shift. The engine calls the FUNC that is the rule's target; the ids inside the kind-4 action are never read (emulated). So the step changes the two rules' slots for the value ELECTRONIC, both 8-byte relocated pointers in RELRO:
  - `0x48bcd90` → null;
  - `0x48baaa8` → load base + `0x3e4fd70`.

  "Invalid" is then called instead of "electronic", the ZV-E1's NO_RESTRICTION path. This takes effect at the next change of the derived key: Movie, then back to a still mode.
  - `build/emu_exclusion_fx30.py` runs the FX30's own `init` (`0x2703004`) and `run_exclusion` (`0x27035d4`), with the state table at `0x820d0b0` and the inhibit counters at `0x81f65f8`.
  - Stock: Flash Mode is forced off and inhibited.
  - With the slots changed, after Movie and back: the re-throwing key is INVALID, Flash Mode is free and its stored value comes back. Wireless stays inhibited.
  - Put back plus Movie and back: stock again.
- **Menus.** 12 class-flag bytes of column 7 (LAX), copied from the FX3's column 6 (RELRO).
- **Shoe table.** `libObj.so`'s InfraHotshoe instance is held from start-up:
  - the instance pointer is at `0x2cde00`;
  - its vtable word is load base + `0x251c38`;
  - the count (42) is at instance + `0x28`;
  - the heap copy of setting `0x01120004` is at instance + `0x60`, 32-byte entries with words 0 and 1 swapped.

  Word 1 of entries 17, 19 and 35 changes from `0x04ffffff` to `0x04000012` / `14` / `24`.
- **Helper.** `fx30flash.c` is its own small helper (no imports). Every read of the process's memory is `pread64` of `/proc/self/mem`, and every write is `pwrite64`, so a bad pointer gives EIO, not a fault.
  - **Guards:** both ELF headers, the bytes beside every site (trimmed at relocated words), both rules' headers and other slots, both action lists, six `libObj.so` code spans, the instance's vtable and count, and all 1,344 bytes of the table apart from the three sites.
  - **Write order:** apply writes the shoe table, then the menus, then the rules; put back runs the reverse; any failure is undone.
  - **Emulation:** `emu_fx30_flash.py`, 33 cases.
- **Not known until an FX30 runs it:**
  - whether the shoe carries the flash contacts and power;
  - the start time the capture sequence gives the scheduler for an electronic-shutter still;
  - the shutter-speed limit with flash: about 1/15 s or 1/30 s from the read-out, and the step sets none;
  - the camera's own menu path to Flash Mode.

## Card-speed check off: `cardspeed_off_fx30_v1` (V18 / V19 / V20), 2026-11-27, not run

The study is in the map (`modding/CARD_SPEED_CHECK.md`, decoder `build/media_rate_check.py`, published here as `tools/modding/fx30/media_rate_check.py`). In short:

- **Where the decision is made.** `libmpr.so` (6.01, SHA-256 `2ba4e927…`), class `RateCheck`:
  - `getMediaTransferRateCheckType_Normal` / `_SnQ` dispatch on the record format (`movieRecParam+0x170`; 9 and 12 = AVC Intra 4K, 10 = AVC Intra FHD) to one leaf per family.
  - Each leaf looks the setting up in a table of rows {quality code `+0x174`, frame-rate class of `+0x178`, flag byte `+0x196`, ..., check type}. No row gives type 0.
  - `GetMediaTransferRateInh` (`0x103c88`, 604 bytes) reads the card's drive info (`Fsys_GetDriveInfo`: `transferRate` at `+0x64` in Mbps, `filesystemType` at `+0x68`) and switches on the type. Its compare helper is `0x103c68`.
- **The check types, measured by running the function in Unicorn:**

  | Type | Card passes when | Inhibit bit | Sony's name |
  |---|---|---|---|
  | 0 | never (setting not in the tables) | `0x400`, returns 3 | UNAVAILABLE_SETTING |
  | 1 | rate ≥ 80 | `0x800` | NEED_OVER_80_MBPS (Class 10 / U1) |
  | 2 | rate > 120 | `0x1000` | NEED_OVER_240_MBPS (V30) |
  | 3 | rate > 400 and exFAT (4) | `0x2000` | NEED_OVER_480_MBPS (V60) |
  | 4 | rate > 600 and exFAT (4) | `0x4000` | NEED_OVER_720_MBPS (V90) |
  | 5 | rate > 1350 | `0x8000` | NEED_OVER_1600_MBPS (VPG200) |
  | 6 | rate > 2700 | `0x8000` | (VPG400) |

- **XAVC S-I rows:** all ten rows of `Normal_AVC_Intra_4K` (`0x307858`) and of `Normal_AVC_Intra_FHD` (`0x307ae0`) ask for type 4 when the flag byte `+0x196` is 0 and type 5 when it is 1. What sets that byte is not traced.
- **Where the card's rate comes from** (`libInfraMediaCommon.so`, `+0xf0` of the media object, read through `libInfraFsys.so`):
  - SD (`mcmn_drv_mmc_open`): speed class 0/2/4/6/10 → 3/16/32/48/80; UHS U1 → 80, U3 → 240; video speed class V30 → 240, V60 → 480, V90 → 720, the last two only on a UHS-II bus.
  - NVMe / CFexpress (`mcmn_drv_nvme_updateinfo`): always 240. A card with Sony's VPG P5 profile and enough PCIe link gets a performance-guarantee rate of `0x1900` / `0x3200` while the guarantee is active (`mcmn_drv_nvme_vpgp5_setpgtype_impl`).
  - So a plain NVMe drive in an adapter passes types 1 and 2 only.
- **How the result reaches the app.** Both callers, `mpr::GetMovieRecStatus` and the movie-status update `0x12b178`, OR the bit into the slot's movie-record status. `appFw.so` turns it into `movie_recording_inhibit_cause_by_system_and_media_rate_slotN`, which four exclusion rules map to "movie not recordable" on that slot (`media_movie_recordable_state_slotN` DISABLE, `media_recordable_state_movie_slotN` NOT_RECORDABLE).
- **The patch:** the two stores of the speed bits become NOPs: `0x103dc8` (types 1 and 2) and `0x103e68` (types 3 to 6), both `str w0, [x19]` (`600200b9` → `1f2003d5`).
  - Type 0 still stores `0x400` and returns 3.
  - The bool output and the return value are unchanged for every input (emulated before and after).
- **Helper.** `fx30cardspeed.c` is its own small helper (no imports); every read and write goes through `/proc/self/mem`.
  - **Guards:** libmpr.so's ELF header and the 636 bytes from the helper to the end of the check, apart from the two sites; the check must lie in an executable mapping of `libmpr.so` at its file offset.
  - **Write order:** apply writes in address order, put back in reverse, read back after each; any failure is undone. The kit's L19 already writes two `libmpr.so` instructions this way.
  - **Emulation:** `emu_fx30_cardspeed.py`, 27 cases; the last ones run the patched code from the model's memory through the decoder's emulation of the check.
- **Not known until an FX30 runs it:**
  - whether a slot's state updates on re-inserting the card, as the two callers suggest, or needs a setting change;
  - whether any other part refuses S-I on a slow card: none was found in `appFw.so`'s exclusion rules, but the caution screens were not traced;
  - how an adapter and drive behave at S-I rates.
- **Other cameras:** the same function, the same thresholds and the same two-store patch were found and emulated in the A7 IV (1.05, 2.01, 6.02), FX2, FX3, FX6, A7S III, A1, A1 II, A9 III, A7C II, ZV-E1 and A6700 (`evidence/media_rate/media_rate_summary.json` in the map).
