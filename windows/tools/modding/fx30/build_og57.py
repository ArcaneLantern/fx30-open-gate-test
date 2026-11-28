"""Build the encoder and container side of a 5760 by 3840 file that rides on the stock 4K recording formats (A7 IV 6.02):
design `ogfile57_v1` (XAVC HS 4K and XAVC S 4K, 23.98p and 25p). Design only: nothing is written to a firmware file and
nothing is sent to a camera.

It is the 5.7K counterpart of ogfile2560_hs_s_v1 (build/build_ogfile.py, which records on the camera, F698) and goes
with the baseline (dmmwb4688_v1 + ogsq_v3) and the coprocessor words of og57cp_v1 (build/build_ram_words.py).

What a 5760 by 3840 picture at 24 frames a second needs that a 3840 by 2560 one did not:

  two encoder cores   22.1 million pixels x 24 = 531 million a second; one core serves the 4K class up to 30p (249 million).
                      Sony's own tables in this file hold the answer: the dormant 5760x3240 format (nine HEVC descriptors,
                      24 to 30p) and every other descriptor that uses both cores have +0x38 = 2, +0x3c = 6, +0x78 = 2,
                      where the one-core 4K descriptors have 0, 1, 0. Their profiles differ from the one-core 4K profile
                      of the same chroma and depth only in the raster, +0x4c (1.5 x the width), +0x56 (rows for the first
                      core: half the picture in coding-block rows), the level, and the fields that follow the quality
                      class (bit rate and buffer figures). This builder checks that statement before it uses it.
  the memory          the codec firmware's own calculation (build/emu_vcd_chmem.py) asks for a reference-picture block of
                      66.4 MB (4:2:0) or 88.5 MB (4:2:2) and a work block of 14.3 or 25.6 MB. The 4K class's blocks are
                      100.8, 50.8, 14.2 and 138.7 MB, handed out as {frame buffer CD, LD, multi, ES} = {0x486, 0x474,
                      0x477, 0x47a}. In that order they do not hold it; as {0x477, 0x486, 0x474, 0x47a} they do
                      (CD needs 5.0 MB). Row 3 of the unit-type table, which a picture above 8,847,360 pixels gets, is
                      written with that order.

Sites:
  libmpr.so   L1  g_videoParamComb rows 0, 2 (XAVC S 4K) and 5, 7 (XAVC HS 4K): 3840x2160 -> 5760x3840
  av-cam.bin  A0  unit-type table row 3 := {0x477, 0x486, 0x474, 0x47a}
              A1  the formats' 3840x2160 descriptors at coding-rate codes 5 and 3, normal speed: +0x38, +0x3c := 2, 6;
                  +0x78 := 2; raster := 5760x3840
              A2  their profiles: the three raster fields (+0x04, +0x34, and +0x8a in an HEVC profile, +0x8e in an AVC one), +0x4c := 8640, +0x56 := 1920, the level byte := Level 6
                  (HEVC 180, AVC 60: the lowest level whose picture size limit holds 5760 by 3840). `--keep-level`
                  leaves the level bytes as they are
              A3  clip-format row 1 (8192x4320, unused) -> 5760x3840, code 16 (the label of a 4K recording)

The bit-rate fields of the profiles are left alone: the stream gets the bit rate the menu's record setting says.
The container's own raster is left at 3840 by 2160, as in the 3840 by 2560 state.

--rate300 (2026-11-21, a test the owner asked for) makes the design ogfile57r300_v1: the same sites, and in every profile whose bit rate is 97
million or more (the menu's 100M settings) the three rate fields that follow the quality class are written with the figures of Sony's own
dormant 5760x3240 profiles (300, 340, 340 million) and the level byte with theirs (Level 6.1). The lower record settings keep their bit rate.

--m1 (2026-11-24, with --rate300; a test the owner asked for: trial 2 of "Astra Analysis Check/5.7K cadence trials", duplicate frames
at 5.7K) makes the design ogfile57r300m1_v1: ogfile57r300_v1 plus two bytes for the one menu entry XAVC HS 4K, 24p (23.98p), 100M 4:2:2
10-bit (descriptor 406, profile key 101702): the descriptor's PredMode +0x85 and the profile's MParam +0x97 go from 3 to 1. MParam is the
anchor distance M of the GOP: 3 = two B pictures between I/P pictures (picture reordering), 1 = I and P pictures only, coded in display
order. PredMode is what av-cam sends at channel creation (CreateCh); the codec firmware sizes the multi buffer by it. In every stock HEVC
descriptor PredMode equals its profile's MParam (checked below), and Sony's own two-core HEVC profiles of codec 21 (3840x2160 and
1920x1080, 24 to 60p) carry 1 and 1. The other menu entries keep M = 3: they are the control in the same state.

--m1all (2026-11-24, with --rate300; after --m1 recorded with no held frames, F981) makes the design ogfile57r300m1_v2: ogfile57r300_v1 with
M = 1 in EVERY descriptor of the design (XAVC HS 4K and XAVC S 4K, every record setting, 23.98p and 25p: PredMode +0x85 and the profile's
MParam, HEVC +0x97 / AVC +0x9b, 3 -> 1), plus one instruction of libmpr.so: the recorder's writer set-up 0x117da8 stores the video edit
list's start in frames (0x118004 `csinc w0, w0, wzr, eq` -> comb 12: 2, any other: 1; stored at writer +0x28 -> MP4 request +0x10 ->
libXavcMp4 +0x50 -> 0x226818 media_time = frame duration x that count). With M = 3 that one frame is what the B-picture composition
offsets need; with M = 1 there are none, so it hid the first picture and put the video one frame ahead (F981). The site becomes
`mov w0, #0`: media_time 0. That is right only when every recording in the state is M = 1, which is why v2 changes every descriptor.

Run:  work\\venv\\Scripts\\python.exe -I -B build\\build_og57.py [--keep-level] [--rate300 [--m1 | --m1all]] [--list] [--register]
      ... --raster 6912 2880 --name ogfile69_v1 [--goes-with "..."]     the same sites for another picture size (2026-11-20: the 2.4:1 file
                                                                      of the anamorphic-native state; Level 6 either way)
Writes modding/designs/ogfile57_v1.json and poke lists (file offset, hex) for the emulators.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402
import build_ogfile  # noqa: E402
from build_ogfile import AVB, CLIP, COMB, DESC, NDESC, PROFILE_TABLES, RATES, UNIT_TABLE, Design  # noqa: E402
BUILD, SUFFIX, CLIP_8K, CLIP_4K = "a7iv_602", "", 1, 16     # --build <id>: another build's tables (build_ogfile.OTHER_BUILDS)

W0, H0, W1, H1 = 3840, 2160, 5760, 3840
# the 4K descriptors' coding-rate codes (descriptor +8): 2, 3, 5 named in build_ogfile.RATES (F189-F203); 0 and 1 are the 4K 59.94p and 50p rows
# (the menu's 60p/50p settings; one core, +0x78 = 0, at normal speed), 6 and 8 the dormant 119.88p / 100p two-core rows (--rates, 2026-11-26)
RATE_CODE_NAMES = {0: "59.94p", 1: "50p", 2: "29.97p", 3: "25p", 5: "23.98p", 6: "119.88p", 8: "100p"}
NAME = "ogfile57_v1"
UNIT_ROW = (0x477, 0x486, 0x474, 0x47A)             # frame buffer CD, LD, multi buffer, ES buffer
FAMILIES = {
    "hs": {"title": "XAVC HS 4K (HEVC)", "codec": 0xE, "comb_codec": 1, "level6": 180, "level61": 183, "rate_off": 0xAC, "level_off": 0x9E, "block_rows": 32, "raster3": 0x8A,
           "combs": {5: "HEVC 4:2:0 10-bit", 7: "HEVC 4:2:2 10-bit"}, "groups": {(0, 1): "4:2:0 10-bit", (1, 1): "4:2:2 10-bit"},
           "reference_raster": (5760, 3240)},
    "s": {"title": "XAVC S 4K (AVC)", "codec": 4, "comb_codec": 0, "level6": 60, "level61": 61, "rate_off": 0xB0, "level_off": 0xA7, "block_rows": 16, "raster3": 0x8E,
          "combs": {0: "AVC 4:2:0 8-bit", 2: "AVC 4:2:2 10-bit"}, "groups": {(0, 0): "4:2:0 8-bit", (1, 1): "4:2:2 10-bit"},
          "reference_raster": (7680, 4320)},
}
WHY = ("the owner asked for a camera recording test at 5760 by 3840 (2026-11-18), after the 3840 by 2560 file in XAVC HS 4K and XAVC S 4K "
       "(F698, F700); this is its encoder side")
GOES_WITH = "dmmwb4688_v1 + ogsq_v3 (the baseline) and og57cp_v1 (output size, four scaler engines, the output buffer), all in coprocessor RAM"


def table(av):
    rows = []
    for k in range(NDESC):
        o = DESC + k * 0x90
        f = struct.unpack_from("<7I", av, o)
        rows.append({"k": k, "o": o, "codec": f[0], "infr": f[1], "codfr": f[2], "f0c": f[3], "cls": f[4], "chroma": f[5], "bitl": f[6],
                     "key": struct.unpack_from("<I", av, o + 0x28)[0], "wh": struct.unpack_from("<HH", av, o + 0x7E), "core": av[o + 0x78],
                     "w38": struct.unpack_from("<II", av, o + 0x38)})
    return rows


def reference_check(av, rows, prof_off, f):
    """Sony's own two-core profile of a large raster against the one-core 4K profile of the same chroma, depth and rate: the bytes that differ
    are the raster, +0x4c, +0x56, the level, the key, and bytes that follow the quality class. Returns what was compared."""
    out = []
    lvl = f["level_off"]
    for (chroma, bitl) in f["groups"]:
        four = [r for r in rows if r["codec"] == f["codec"] and r["wh"] == (W0, H0) and r["codfr"] == 5 and not r["infr"] and (r["chroma"], r["bitl"]) == (chroma, bitl)
                and r["core"] == 0]
        big = [r for r in rows if r["codec"] == f["codec"] and r["wh"] == f["reference_raster"] and r["codfr"] == 5 and not r["infr"] and (r["chroma"], r["bitl"]) == (chroma, bitl)]
        if not big:                                   # no reference of this chroma and depth for this codec (AVC 4:2:2 at 7680 wide): the rule is carried over
            out.append({"format": f["groups"][(chroma, bitl)], "reference": None})
            continue
        prof4 = [av[prof_off[r["key"]]:prof_off[r["key"]] + 0x100] for r in four]
        by_class = {o for o in range(0x100) if len({p[o] for p in prof4}) > 1} | set(range(0xAC, 0xC8)) | {0x14}
        key = set(range(0x20, 0x24))
        a = prof4[0]
        for r in big:
            b = av[prof_off[r["key"]]:prof_off[r["key"]] + 0x100]
            diff = {o for o in range(0x100) if a[o] != b[o]} - by_class - key
            assert struct.unpack_from("<HH", a, f["raster3"]) == (W0, H0) and struct.unpack_from("<HH", b, f["raster3"]) == r["wh"], r["k"]
            raster = set(range(4, 8)) | set(range(0x34, 0x3C)) | set(range(f["raster3"], f["raster3"] + 4))
            rest = diff - raster - {0x4C, 0x4D, 0x56, 0x57, lvl}
            rw, rh = r["wh"]
            assert not rest, (f["title"], r["k"], sorted(hex(o) for o in rest))
            assert struct.unpack_from("<H", b, 0x4C)[0] == rw * 3 // 2 and struct.unpack_from("<H", a, 0x4C)[0] == W0 * 3 // 2, r["k"]
            rows_first = struct.unpack_from("<H", b, 0x56)[0]
            n = -(-rh // f["block_rows"])                                     # coding-block rows of the picture
            assert rows_first in ((n // 2) * f["block_rows"], -(-n // 2) * f["block_rows"]), (r["k"], rows_first)
            assert r["core"] == 2 and r["w38"] == (2, 6) and four[0]["w38"] == (0, 1), r["k"]
            out.append({"format": f["groups"][(chroma, bitl)], "reference": "descriptor #%d, %dx%d, quality class %d, key %d" % (r["k"], rw, rh, r["cls"], r["key"]),
                        "against": "descriptor #%d, key %d" % (four[0]["k"], four[0]["key"]), "rows_for_first_core": rows_first, "level_byte": b[lvl],
                        "bytes_that_differ_outside_class_and_key": sorted(hex(o) for o in diff)})
    return out


RATE_NAMES = ("bit rate", "highest bit rate", "stream buffer")
RATE_ROWS = []                                      # --rate300: one entry per profile whose rate fields the design writes


def rate_figures(six):
    """The six words that follow the quality class in a profile, as three (shift, value) pairs. Read by their values in Sony's profiles (not from
    the code that uses them): a rate is value << (6 + shift), the buffer is value << (4 + shift) bits. The 100M settings give 97.0, 100.0, 100.0
    million; Sony's dormant 5760x3240 format gives 300.0, 339.9, 340.0 million."""
    s0, v0, s1, v1, s2, v2 = six
    return [v0 << (6 + s0), v1 << (6 + s1), v2 << (4 + s2)]


def rate300_reference(av, rows, prof_off):
    """The rate fields and the level of Sony's own 300 Mbps profiles: the dormant 5760x3240 HEVC format (quality class 15), all chromas and rates."""
    ref = [r for r in rows if r["codec"] == 0xE and r["wh"] == (5760, 3240) and r["cls"] == 15 and not r["infr"]]
    figs = {av[prof_off[r["key"]] + 0xAC:prof_off[r["key"]] + 0xC4] for r in ref}
    assert len(ref) >= 3 and len(figs) == 1 and {av[prof_off[r["key"]] + 0x9E] for r in ref} == {FAMILIES["hs"]["level61"]}, "Sony's 300 Mbps profiles are not as read"
    six = figs.pop()
    assert struct.unpack("<6I", six) == (2, 1171874, 9, 10374, 7, 166014) and rate_figures(struct.unpack("<6I", six)) == [299999744, 339935232, 339996672]
    # AVC has no profile at these figures. Its fields have the same form four bytes on (checked per profile in build()), and Sony's own 7680-wide
    # AVC profiles carry Level 6 at 200 Mbps and Level 6.1 at 400 Mbps (H.264 High at Level 6 ends at 300 Mbps, and the highest rate here is 340).
    for cls, want in ((21, 60), (13, 61)):
        got = {av[prof_off[r["key"]] + 0xA7] for r in rows if r["codec"] == 4 and r["wh"] == (7680, 4320) and r["cls"] == cls and r["codfr"] == 5 and not r["infr"]}
        assert got == {want}, (cls, got)
    return six, sorted(r["k"] for r in ref)


M1_PRED, M1_MPARAM = 0x85, 0x97                     # --m1: descriptor PredMode (sent at CreateCh), HEVC profile MParam (EncConfig +0x18, F646)
M1_MPARAM_FAM = {"hs": 0x97, "s": 0x9B}             # --m1all: the start-block builder's HEVC and AVC branches (0xffffffc0012174c0)
ELST_SITE = 0x118004                                # --m1all: libmpr.so, writer set-up 0x117da8: the edit list's start in frames
ELST_VERSION = "v3"                                 # --m1all builds v3; --m1all --v2 rebuilds v2 (its site 0x118004 changed nothing on the camera, F986)
ELST_V3_SITE, ELST_V3_TABLE = 0x11F4E0, 0x2E9080    # writer set-up 0x11f030: the HEVC branch of the edit list's start; mpr::pconv::m_vpcSt
ELST_V3_CODE = ([(0x11F4CC, "cmp", "w0, #1"), (0x11F4D0, "b.ne", "#0x11fe60"), (0x11F4D4, "sub", "w1, w1, #4"), (0x11F4D8, "cmp", "w1, #7"),
                 (0x11F4DC, "mov", "w1, #2"), (0x11F4E0, "csel", "w0, w1, w0, ls"), (0x11F4E4, "str", "w0, [x29, #0xb40]")],
                [(0x11FE5C, "cbnz", "w0, #0x11f4e8"), (0x11FE60, "mov", "w0, #1"), (0x11FE64, "b", "#0x11f4e4")])
ELST_CODE = [(0x117FFC, "cmp", "w0, #0xc"), (0x118000, "mov", "w0, #2"), (0x118004, "csinc", "w0, w0, wzr, eq"), (0x118008, "mov", "w1, #7"),
             (0x11800C, "add", "x2, x29, #0x70"), (0x118010, "str", "w0, [x19, #0x28]")]
# A7C II 2.01 (2026-11-25): the same writer set-up, its HEVC branch found by its instructions (sub/cmp/mov/csel) at 0x11e414; the AVC branch at
# 0x11ed88; mpr::pconv::m_vpcSt byte-identical at 0x2e3738. Only v3 (0x11f4e0's form) is built for it.
ELST_BUILDS = {"a7c2_201": {"site": 0x11E420, "table": 0x2E3738,
                            "code": ([(0x11E40C, "cmp", "w0, #1"), (0x11E410, "b.ne", "#0x11ed8c"), (0x11E414, "sub", "w1, w1, #4"), (0x11E418, "cmp", "w1, #7"),
                                      (0x11E41C, "mov", "w1, #2"), (0x11E420, "csel", "w0, w1, w0, ls"), (0x11E424, "str", "w0, [x29, #0xba8]")],
                                     [(0x11ED88, "cbnz", "w0, #0x11e428"), (0x11ED8C, "mov", "w0, #1"), (0x11ED90, "b", "#0x11e424")])}}
# FX2 1.01 (2026-11-27, the FX2's 5.7K port, GitHub issue 7): the same writer set-up; its HEVC branch found by the same four instructions
# (sub/cmp/mov/csel, one hit in the whole library) at 0x11e400, 0x60 before the call of the track config 0x21f364 (0x11e46c), as on the A7 IV
# (0x11f4e0 / 0x11f540); the AVC branch at 0x11ed74; mpr::pconv::m_vpcSt byte-identical (the A7 IV's first 8 rows, once) at 0x2e3898.
ELST_BUILDS["fx2_101"] = {"site": 0x11E40C, "table": 0x2E3898,
                          "code": ([(0x11E3F8, "cmp", "w0, #1"), (0x11E3FC, "b.ne", "#0x11ed78"), (0x11E400, "sub", "w1, w1, #4"), (0x11E404, "cmp", "w1, #7"),
                                    (0x11E408, "mov", "w1, #2"), (0x11E40C, "csel", "w0, w1, w0, ls"), (0x11E410, "str", "w0, [x29, #0xca8]")],
                                   [(0x11ED74, "cbnz", "w0, #0x11e414"), (0x11ED78, "mov", "w0, #1"), (0x11ED7C, "b", "#0x11e410")])}
# FX30 6.01 (2026-11-28, the FX30's 5.7K step): the same writer set-up in the FX3's relinked body; its HEVC branch found by the same four
# instructions (sub/cmp/mov/csel, one hit in the whole library) at 0x11d5d8, 0x60 before the call of the track config 0x21fef0 (0x11d644); the
# AVC branch at 0x11df28; mpr::pconv::m_vpcSt (the A7 IV's first 64 bytes, once) at 0x2e0bb0.
ELST_BUILDS["fx30_601"] = {"site": 0x11D5E4, "table": 0x2E0BB0,
                           "code": ([(0x11D5D0, "cmp", "w0, #1"), (0x11D5D4, "b.ne", "#0x11df2c"), (0x11D5D8, "sub", "w1, w1, #4"), (0x11D5DC, "cmp", "w1, #7"),
                                     (0x11D5E0, "mov", "w1, #2"), (0x11D5E4, "csel", "w0, w1, w0, ls"), (0x11D5E8, "str", "w0, [x29, #0xc30]")],
                                    [(0x11DF28, "cbnz", "w0, #0x11d5ec"), (0x11DF2C, "mov", "w0, #1"), (0x11DF30, "b", "#0x11d5e8")])}
# the words of another build's 5.7K step (the A7C II's are the text its designs were first written with)
SUFFIX_TEXTS = {"fx30_601": {
    "why": ("the FX30's 5.7K open gate (2026-11-28; the owner: 'does our FX30 open gate patch have 5.7K and 300mbps mode with no B frames? If not "
            "can we update'): the A7 IV's 5.7K encoder step ogfile57r300m1_v4 (300 Mbps on the 100M settings, M = 1 everywhere, the HEVC edit "
            "list at 0, the MP4 headers saying 5760x3840), on the FX30's tables"),
    "why_v3": ("the --no-meta form of the FX30's 5.7K encoder step: ogfile57r300m1_fx30_v4 without the MP4 header sites (the A7 IV's "
               "ogfile57r300m1_v3 on the FX30's tables)"),
    "goes_with": "og57n_fx30_v1 (the real 5760x3840 picture from the 5952x3968 window) and og57cp_fx30_v1, all in coprocessor RAM",
    "checked": "build/emu_mp4_meta.py --build fx30_601 --both -> evidence/fx30/encoder/mp4_meta_emu_fx30_both.json"},
                "fx2_101": {
    "why": ("the FX2's 5.7K open gate (GitHub issue 7, 2026-11-27; the owner: 'port 5.7K 300mbps from the A7iv ... for parity, PAL too'): the A7 IV's 5.7K "
            "encoder step ogfile57r300m1_v4 (M = 1 everywhere, the HEVC edit list at 0, the MP4 headers saying 5760x3840), on the FX2's tables"),
    "why_v3": ("the --no-meta form of the FX2's 5.7K encoder step (GitHub issue 7): ogfile57r300m1_fx2_v4 without the MP4 header sites (the A7 IV's "
               "ogfile57r300m1_v3 on the FX2's tables)"),
    "goes_with": "dmmwb4688_fx2_v1 + og57n_fx2_v1 or og57n880_fx2_v1 (the real 5760x3840 picture) and og57cp_fx2_v3, all in coprocessor RAM",
    "checked": "build/emu_mp4_meta.py --build fx2_101 --both -> evidence/fx2/mp4_meta_emu_fx2_both.json"}}
M1_TARGET = {"family": "hs", "format": "4:2:2 10-bit", "coding_rate_code": 5}   # XAVC HS 4K, 24p (23.98p), and among those the 100M setting
M1_ROWS, M1_INFO = [], {}
META, META_INFO = False, {}                         # --meta (build/mp4_meta_sites.py)


def m1_reference(av, rows, prof_off):
    """The rule the --m1 sites keep, read from Sony's tables: in every HEVC descriptor whose profile is in the HEVC tables, PredMode (+0x85) equals
    the profile's MParam (+0x97); and Sony's own two-core HEVC profiles with M = 1 (codec 21) exist at 3840x2160 and at 23.98p."""
    pairs, mism = {}, []
    for r in rows:
        po = prof_off.get(r["key"])
        if po is None or av[r["o"] + 0x84] != 2:      # CodecType 2 = HEVC
            continue
        p, m = av[r["o"] + M1_PRED], av[po + M1_MPARAM]
        pairs[(r["codec"], p, m)] = pairs.get((r["codec"], p, m), 0) + 1
        if p != m:
            mism.append(r["k"])
    assert not mism, f"HEVC descriptors whose PredMode differs from the profile's MParam: {mism}"
    two_core_m1 = [r for r in rows if r["codec"] == 21 and r["core"] == 2 and av[r["o"] + M1_PRED] == 1 and av[prof_off[r["key"]] + M1_MPARAM] == 1]
    uhd = sorted(r["k"] for r in two_core_m1 if r["wh"] == (3840, 2160))
    p2398 = sorted(r["k"] for r in two_core_m1 if r["codfr"] == 5)
    assert uhd and p2398, "Sony's two-core M = 1 HEVC profiles are not as read"
    return {"hevc_codec_pred_mode_m_param_counts": [{"codec": c, "pred_mode": p, "m_param": m, "descriptors": n} for (c, p, m), n in sorted(pairs.items())],
            "rule": "PredMode == MParam in every HEVC descriptor (%d)" % sum(pairs.values()),
            "sonys_two_core_m1_hevc_3840x2160": uhd, "sonys_two_core_m1_hevc_23_98p": p2398}


def m1all_reference(av, rows, prof_off):
    """--m1all: the rule for both codecs (HEVC MParam +0x97, AVC +0x9b), and Sony's own two-core M = 1 profiles of each codec at 3840 wide or more."""
    pairs, mism = {}, []
    for r in rows:
        po, ct = prof_off.get(r["key"]), av[r["o"] + 0x84]
        if po is None or ct not in (1, 2):           # CodecType 1 = AVC, 2 = HEVC
            continue
        p, m = av[r["o"] + M1_PRED], av[po + (0x97 if ct == 2 else 0x9B)]
        pairs[(r["codec"], ct, p, m)] = pairs.get((r["codec"], ct, p, m), 0) + 1
        if p != m:
            mism.append(r["k"])
    assert not mism, f"descriptors whose PredMode differs from the profile's MParam: {mism}"
    big = {ct: sorted(r["k"] for r in rows if av[r["o"] + 0x84] == ct and r["core"] == 2 and r["wh"][0] >= 3840 and av[r["o"] + M1_PRED] == 1
                      and r["key"] in prof_off and av[prof_off[r["key"]] + (0x97 if ct == 2 else 0x9B)] == 1) for ct in (1, 2)}
    assert big[1] and big[2], "Sony's two-core M = 1 profiles at 3840 wide are not as read"
    return {"codec_codectype_pred_mode_m_param_counts": [{"codec": c, "codec_type": t, "pred_mode": p, "m_param": m, "descriptors": n}
                                                         for (c, t, p, m), n in sorted(pairs.items())],
            "rule": "PredMode == MParam in every AVC and HEVC descriptor (%d)" % sum(pairs.values()),
            "sonys_two_core_m1_avc_3840_wide": big[1], "sonys_two_core_m1_hevc_3840_wide": big[2]}


def build(lm, av, keep_level, rate300=False, m1=False, m1all=False):
    d = Design(NAME, f"A {W1} by {H1} file on XAVC HS 4K and XAVC S 4K at {' and '.join(RATES[c] for c in sorted(RATES, reverse=True))}: encoder request, two encoder cores, the 4K memory blocks in an order "
                     "that holds the picture, descriptors, profiles and the monitoring label")
    rows = table(av)
    prof_off = {}
    for base, n in PROFILE_TABLES:
        for k in range(n):
            prof_off.setdefault(struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0], []).append(base + k * 0x100)
    assert all(len(v) == 1 for k, v in prof_off.items() if any(r["key"] == k and r["codec"] in (4, 0xE) for r in rows))
    prof_off = {k: v[0] for k, v in prof_off.items()}
    # every long-GOP descriptor of this file from 3840 wide up follows the core rule the design copies (the HD ones have other values at +0x3c)
    for r in rows:
        if r["codec"] in (4, 0xE) and r["wh"][0] >= W0:
            assert (r["core"], r["w38"]) in ((0, (0, 1)), (2, (2, 6))), (r["k"], r["core"], r["w38"])
    refs = {fam: reference_check(av, rows, prof_off, f) for fam, f in FAMILIES.items()}
    fast, fast_from = rate300_reference(av, rows, prof_off) if rate300 else (None, None)
    assert not (rate300 and keep_level), "--rate300 writes the level Sony's 300 Mbps profiles carry"
    # ---- libmpr
    for fam, f in FAMILIES.items():
        for row, name in f["combs"].items():
            o = COMB + 0x18 * row
            codec, w, h = struct.unpack_from("<IHH", lm, o)
            assert (codec, w, h) == (f["comb_codec"], W0, H0), (row, codec, w, h)
            d.add("libmpr.so", lm, "L1-comb", o + 4, struct.pack("<HH", W1, H1), f"g_videoParamComb row {row} ({name}): {W0}x{H0} -> {W1}x{H1} (the encoder request's raster)",
                  struct.pack("<HH", W0, H0))
    # ---- av-cam: the memory blocks
    urows = [struct.unpack_from("<4I", av, UNIT_TABLE + 0x10 * k) for k in range(5)]
    assert urows[2] == (0x486, 0x474, 0x477, 0x47A) and urows[3] == (0, 0x473, 0x476, 0x479) and sorted(UNIT_ROW) == sorted(urows[2])
    d.add("av-cam.bin", av, "A0-unit", UNIT_TABLE + 0x30, struct.pack("<4I", *UNIT_ROW),
          "unit-type table row 3 (above 8,847,360 pixels; ids 0, 0x473, 0x476, 0x479, none of which has memory on this camera) := the 4K class's four "
          "blocks in another order: frame buffer CD 0x477 (14.2 MB), LD 0x486 (100.8 MB), multi buffer 0x474 (50.8 MB), ES buffer 0x47a (138.7 MB)",
          struct.pack("<4I", *urows[3]))
    # ---- av-cam: descriptors and profiles
    picked, done = [], set()
    key_users = {}
    for r in rows:
        key_users.setdefault(r["key"], []).append(r)
    for fam, f in FAMILIES.items():
        mine = [r for r in rows if r["wh"] == (W0, H0) and r["codec"] == f["codec"] and (r["chroma"], r["bitl"]) in f["groups"] and r["codfr"] in RATES and not r["infr"]]
        assert mine and {f["groups"][(r["chroma"], r["bitl"])] for r in mine} == set(f["groups"].values())
        rows_first = (-(-H1 // f["block_rows"]) // 2) * f["block_rows"]
        # half the picture in whole coding-block rows, as in Sony's own two-core profiles (reference_check: 1632 of 3240 rows, 2160 of 4320)
        assert rows_first % f["block_rows"] == 0 and abs(2 * rows_first - H1) < 2 * f["block_rows"] and (H1 != 3840 or rows_first == 1920)
        for r in mine:
            o, fmt = r["o"], f["groups"][(r["chroma"], r["bitl"])]
            assert r["core"] == 0 and r["w38"] == (0, 1), r["k"]
            what = f"descriptor #{r['k']} ({f['title']}, {fmt}, {RATES[r['codfr']]}, quality class {r['cls']}, key {r['key']})"
            d.add("av-cam.bin", av, "A1-desc", o + 0x38, struct.pack("<II", 2, 6), what + ": +0x38, +0x3c: 0, 1 -> 2, 6 (as every two-core descriptor of this file)",
                  struct.pack("<II", 0, 1))
            old = av[o + 0x78:o + 0x82]
            assert old[0] == 0 and struct.unpack_from("<HH", old, 6) == (W0, H0)
            d.add("av-cam.bin", av, "A1-desc", o + 0x78, b"\x02" + old[1:6] + struct.pack("<HH", W1, H1),
                  what + f": UseCore +0x78: 0 -> 2; raster +0x7e: {W0}x{H0} -> {W1}x{H1} (the five bytes between are written as they are)", old)
            picked.append({"descriptor": r["k"], "family": fam, "format": fmt, "rate": RATES[r["codfr"]], "coding_rate_code": r["codfr"], "input_rate": r["infr"],
                           "quality_class": r["cls"], "f0c": r["f0c"], "profile_key": r["key"], "pred_mode": av[o + 0x85]})
            if r["key"] in done:
                continue
            done.add(r["key"])
            others = [x["k"] for x in key_users[r["key"]] if x not in mine]
            assert not others, f"profile key {r['key']} is also used by descriptors outside the design: {others}"
            po = prof_off[r["key"]]
            pk = f"profile key {r['key']}"
            assert struct.unpack_from("<HH", av, po + 4) == (W0, H0) and struct.unpack_from("<II", av, po + 0x34) == (W0, H0), r["key"]
            d.add("av-cam.bin", av, "A2-profile", po + 4, struct.pack("<HH", W1, H1), pk + f": raster +0x04 -> {W1}x{H1}", struct.pack("<HH", W0, H0))
            d.add("av-cam.bin", av, "A2-profile", po + 0x34, struct.pack("<II", W1, H1), pk + f": raster +0x34 -> {W1}x{H1}", struct.pack("<II", W0, H0))
            d.add("av-cam.bin", av, "A2-profile", po + f["raster3"], struct.pack("<HH", W1, H1), pk + ": raster +%#x -> %dx%d" % (f["raster3"], W1, H1), struct.pack("<HH", W0, H0))
            old = av[po + 0x4C:po + 0x58]
            assert struct.unpack_from("<H", old, 0)[0] == W0 * 3 // 2 and struct.unpack_from("<H", old, 10)[0] == 0, (r["key"], old.hex())
            d.add("av-cam.bin", av, "A2-profile", po + 0x4C, struct.pack("<H", W1 * 3 // 2) + old[2:10] + struct.pack("<H", rows_first),
                  pk + f": +0x4c: {W0 * 3 // 2} -> {W1 * 3 // 2} (1.5 x the width, as in Sony's profiles); rows for the first core +0x56: 0 -> {rows_first} "
                       "(half the picture; the eight bytes between are written as they are)", old)
            picked[-1]["level_byte"] = av[po + f["level_off"]]
            ro = f["rate_off"]
            cur = struct.unpack_from("<6I", av, po + ro)
            assert all(s < 16 for s in cur[0::2]) and 5_000_000 < rate_figures(cur)[0] <= rate_figures(cur)[1] < 450_000_000, (r["key"], cur)   # the fields have the form read
            if rate300 and rate_figures(cur)[0] >= 96_000_000:           # the menu's 100M settings (97.0 million) and any higher one of the format
                now = rate_figures(cur)
                for j, nm in enumerate(RATE_NAMES):
                    d.add("av-cam.bin", av, "A2-rate", po + ro + 8 * j, fast[8 * j:8 * j + 8],
                          pk + ": %s +%#x: %.1f -> %.1f million (shift and value %d, %d -> %d, %d; the figures of Sony's own 5760x3240 profiles)"
                          % (nm, ro + 8 * j, now[j] / 1e6, rate_figures(struct.unpack("<6I", fast))[j] / 1e6, cur[2 * j], cur[2 * j + 1], *struct.unpack_from("<II", fast, 8 * j)),
                          av[po + ro + 8 * j:po + ro + 8 * j + 8])
                d.add("av-cam.bin", av, "A2-level", po + f["level_off"], bytes([f["level61"]]),
                      pk + f": level {av[po + f['level_off']]} -> {f['level61']} (Level 6.1: " + ("the level of Sony's own 300 Mbps 5760x3240 profiles)" if fam == "hs" else
                                                                                               "Sony's 7680-wide AVC profiles carry it above the rates Level 6 allows)"))
                RATE_ROWS.append({"profile_key": r["key"], "family": fam, "format": fmt, "rate": RATES[r["codfr"]], "quality_class": r["cls"],
                                  "stock_millions": [round(x / 1e6, 1) for x in now], "design_millions": [round(x / 1e6, 1) for x in rate_figures(struct.unpack("<6I", fast))],
                                  "figures_from": "Sony's 5760x3240 profiles, descriptors %s" % fast_from if fam == "hs" else "the HEVC figures, in the AVC profile's own fields (no AVC profile has them)"})
                continue
            if not keep_level:
                d.add("av-cam.bin", av, "A2-level", po + f["level_off"], bytes([f["level6"]]),
                      pk + f": level {av[po + f['level_off']]} -> {f['level6']} (Level 6: the lowest level whose picture size limit holds {W1} by {H1}; "
                           "Sony's 7680-wide profiles of the same bit-rate range carry it)")
    # ---- av-cam: --m1, I and P pictures only for the 100M 4:2:2 10-bit setting of XAVC HS 4K at 23.98p
    m1_ref = None
    if m1:
        assert rate300, "--m1 goes on top of the 300 Mbps design"
        m1_ref = m1_reference(av, rows, prof_off)
        fast_keys = {x["profile_key"] for x in RATE_ROWS}
        tgt = [p for p in picked if all(p[k] == v for k, v in M1_TARGET.items()) and p["profile_key"] in fast_keys]
        assert len(tgt) == 1, f"one descriptor expected for the 100M 4:2:2 10-bit setting at 23.98p: {tgt}"
        p = tgt[0]
        o, po = DESC + p["descriptor"] * 0x90, prof_off[p["profile_key"]]
        if BUILD == "a7iv_602":                      # the offsets the owner's trial note names (Astra Analysis Check/5.7K cadence trials/README.md)
            assert (p["descriptor"], p["profile_key"], o + M1_PRED, po + M1_MPARAM) == (406, 101702, 0x391E21, 0x3B5463), (p, hex(o + M1_PRED), hex(po + M1_MPARAM))
        assert av[o + M1_PRED] == 3 and av[po + M1_MPARAM] == 3 and struct.unpack_from("<HH", av, po + 0x98) == (24, 24) and av[po + 0xC8] == 0
        what = f"descriptor #{p['descriptor']} (XAVC HS 4K (HEVC), 4:2:2 10-bit, 23.98p, quality class {p['quality_class']}, key {p['profile_key']}; the menu's 100M setting)"
        d.add("av-cam.bin", av, "A4-pred", o + M1_PRED, b"\x01",
              what + ": PredMode +0x85: 3 -> 1 (sent at channel creation; the codec firmware sizes the multi buffer by it: 25,559,040 -> 12,845,056 bytes "
                     "at 5760x3840 4:2:2 10-bit)", b"\x03")
        d.add("av-cam.bin", av, "A4-mparam", po + M1_MPARAM, b"\x01",
              f"profile key {p['profile_key']}: MParam +0x97: 3 -> 1 (EncConfig +0x18: the GOP's anchor distance M; 1 = I and P pictures only, no "
              "picture reordering; NParam/NdParam stay 24/24)", b"\x03")
        p["pred_mode_design"], p["m_param_design"] = 1, 1
        M1_ROWS.append({"descriptor": p["descriptor"], "profile_key": p["profile_key"], "pred_mode_file_off": hex(o + M1_PRED),
                        "m_param_file_off": hex(po + M1_MPARAM), "stock": [3, 3], "design": [1, 1], "n_param_nd_param": [24, 24]})
    # ---- --m1all: M = 1 in every descriptor of the design, and the recorder's edit list without its one-frame start
    if m1all:
        assert rate300 and not m1, "--m1all goes on top of the 300 Mbps design, instead of --m1"
        M1_INFO["rule_checked_against_sonys_tables"] = m1all_reference(av, rows, prof_off)
        for p in picked:
            fam = p["family"]
            mo = M1_MPARAM_FAM[fam]
            o, po = DESC + p["descriptor"] * 0x90, prof_off[p["profile_key"]]
            assert av[o + 0x84] == (2 if fam == "hs" else 1) and av[o + M1_PRED] == 3 and av[po + mo] == 3, p
            nn = struct.unpack_from("<HH", av, po + mo + 1)
            what = (f"descriptor #{p['descriptor']} ({FAMILIES[fam]['title']}, {p['format']}, {p['rate']}, quality class {p['quality_class']}, "
                    f"key {p['profile_key']})")
            d.add("av-cam.bin", av, "A4-pred", o + M1_PRED, b"\x01", what + ": PredMode +0x85: 3 -> 1 (sent at channel creation)", b"\x03")
            d.add("av-cam.bin", av, "A4-mparam", po + mo, b"\x01",
                  f"profile key {p['profile_key']}: MParam {mo:#x}: 3 -> 1 (EncConfig +0x18: I and P pictures only, no picture reordering; "
                  f"NParam/NdParam stay {nn[0]}/{nn[1]})", b"\x03")
            p["pred_mode_design"], p["m_param_design"] = 1, 1
            M1_ROWS.append({"descriptor": p["descriptor"], "family": fam, "format": p["format"], "rate": p["rate"], "quality_class": p["quality_class"],
                            "profile_key": p["profile_key"], "pred_mode_file_off": hex(o + M1_PRED), "m_param_file_off": hex(po + mo),
                            "stock": [3, 3], "design": [1, 1], "n_param_nd_param": list(nn)})
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        new = struct.pack("<I", 0x52800000)                       # movz w0, #0
        if ELST_VERSION == "v3":
            # the normal recording's writer set-up 0x11f030 (F986): the HEVC branch only; AVC keeps its frame (its constant ctts needs it)
            for span in ELST_V3_CODE:
                got = [(i.address, i.mnemonic, i.op_str) for i in md.disasm(lm[span[0][0]:span[-1][0] + 4], span[0][0])]
                assert got == span, f"libmpr.so writer set-up 0x11f030 is not as read: {got}"
            for comb, codec in ((0, 0), (2, 0), (5, 1), (7, 1)):     # mpr::pconv::m_vpcSt: codec word, intra flag 0 for the four formats of the state
                assert struct.unpack_from("<I", lm, ELST_V3_TABLE + 0x1C * comb)[0] == codec and struct.unpack_from("<I", lm, ELST_V3_TABLE + 0x1C * comb + 0x18)[0] == 0
            d.add("libmpr.so", lm, "L3-elst", ELST_V3_SITE, new,
                  "writer set-up 0x11f030 (a normal recording): the video edit list's start in frames, MP4 request +0x10 (0x222b18 -> libXavcMp4 +0x50 -> "
                  "0x226818: media_time = frame duration x it). HEVC branch: `csel w0, w1, w0, ls` (2 frames at 50p and up, else 1) -> `mov w0, #0`. AVC "
                  "(0x11fe60: 1 frame), intra formats and the [x21+4] path unchanged. With M = 1 an HEVC stream has no composition offsets, so a "
                  "one-frame start hides its first picture (F981, F986)", lm[ELST_V3_SITE:ELST_V3_SITE + 4], code=True)
            M1_INFO["edit_list"] = {
                "site": hex(ELST_V3_SITE), "function": "0x11f030 (the writer set-up of a normal recording; it calls the track builder 0x222b18 at 0x11f540)",
                "stock": "intra flag -> 0; [x21+4] set -> HEVC 0, AVC 1; otherwise AVC 1, HEVC 2 for frame-rate codes 4-11 else 1 (csel at 0x11f4e0)",
                "design": "mov w0, #0 at 0x11f4e0 -> HEVC 0 on the normal path; nothing else changes (build/emu_elst_site_v3.py, every comb, rate code and flag)",
                "why_not_0x118004": "F982 changed 0x118004 in 0x117da8 (another caller of 0x222b18, 0x1179ac, reached through a pointer); on the camera it "
                                    "changed nothing (C0556 HEVC and C0557 AVC both still start one frame in, F986), so it is left stock here",
                "avc": "AVC keeps one frame: its encoder gives every picture a one-frame composition offset even with M = 1 (C0557: ctts 1001 throughout), "
                       "which that frame cancels",
                "table": hex(ELST_V3_TABLE) + " mpr::pconv::m_vpcSt (7 words a comb: codec, ..., intra flag +0x18)"}
        else:
            got = [(i.address, i.mnemonic, i.op_str) for i in md.disasm(lm[ELST_CODE[0][0]:ELST_CODE[-1][0] + 4], ELST_CODE[0][0])]
            assert got == ELST_CODE, f"libmpr.so writer set-up is not as read: {got}"
        assert [(i.mnemonic, i.op_str) for i in md.disasm(new, ELST_SITE)] == [("mov", "w0, #0")]
        if ELST_VERSION == "v2":
          d.add("libmpr.so", lm, "L3-elst", ELST_SITE, new,
              "writer set-up 0x117da8: the video edit list's start in frames (stored at writer +0x28, then MP4 request +0x10, libXavcMp4 +0x50; "
              "0x226818 makes media_time = frame duration x it): `csinc w0, w0, wzr, eq` (comb 12: 2, any other: 1) -> `mov w0, #0`. "
              "With M = 1 there are no composition offsets, so a one-frame start hides the first picture (F981)", lm[ELST_SITE:ELST_SITE + 4], code=True)
        if ELST_VERSION == "v2":
          M1_INFO["edit_list"] = {
            "site": hex(ELST_SITE), "function": "0x117da8 (recorder writer set-up, F133/F201)",
            "stock": "csinc w0, w0, wzr, eq  ->  comb 12: 2, any other: 1 frame", "design": "mov w0, #0  ->  0 frames",
            "path": "str w0, [x19, #0x28] (0x118010) -> 0x1179ac copies writer +0x28 to the MP4 request +0x10 (0x117a1c) -> 0x222b18 stores it at "
                    "libXavcMp4 +0x50 -> 0x226c44 copies the config -> 0x226818: media_time = FUN_0022637c (frame duration) x it",
            "other_readers": "none: the only 32-bit load of writer +0x28 in 0x116000-0x120000 besides 0x117a1c is 0x11e3f4, the in-camera edit path's "
                             "own structure (0x11e30c, called from 0x11f030 only)",
            "guards": [hex(a) for a, _, _ in ELST_CODE if a != ELST_SITE]}
    # ---- av-cam: the monitoring label
    assert struct.unpack_from("<4I", av, CLIP + 0x10) == (1, 8192, 4320, CLIP_8K) and struct.unpack_from("<4I", av, CLIP + 0x50) == (1, W0, H0, CLIP_4K)
    d.add("av-cam.bin", av, "A3-clip", CLIP + 0x14, struct.pack("<3I", W1, H1, CLIP_4K),
          f"clip-format row 1 (8192x4320, code {CLIP_8K}; unused on this camera) -> {W1}x{H1}, code {CLIP_4K}, the code row 5 gives a 3840x2160 recording. Row 5 is left as it is",
          struct.pack("<3I", 8192, 4320, CLIP_8K))
    # ---- libmpr: --meta, the MP4 headers (tkhd, stsd, Sony's PROF) say the stream's own size (build/mp4_meta_sites.py; checked by
    # build/emu_mp4_meta.py: stsd and PROF built at 5760x3840 with the stock profile ids and pixel aspect 1:1)
    if META:
        import mp4_meta_sites
        meta = mp4_meta_sites.sites(W1, H1, BUILD)
        mp4_meta_sites.check(lm, meta)
        for a, new, want, why in meta:
            d.add("libmpr.so", lm, "L4-mp4size", a, new, why + f" (`{want[0]} {want[1]}` -> `mov`)", lm[a:a + 4], code=True)
        META_INFO.update({"sites": [{"file_off": hex(a), "stock": f"{w[0]} {w[1]}", "note": why} for a, _, w, why in meta],
                          "guards": mp4_meta_sites.guards(lm, meta)})
    spans = sorted((p["binary"], int(p["file_off"], 16), len(p["new"]) // 2) for p in d.patches)
    assert all(a[0] != b[0] or a[1] + a[2] <= b[1] for a, b in zip(spans, spans[1:])), "sites overlap"
    assert all(len(p["new"]) // 2 <= 16 for p in d.patches)
    if m1:
        M1_INFO["rule_checked_against_sonys_tables"] = m1_ref
    return d, picked, refs


def main():
    global W1, H1, NAME, WHY, GOES_WITH, BUILD, SUFFIX, CLIP_8K, CLIP_4K, COMB, DESC, PROFILE_TABLES, UNIT_TABLE, CLIP, NDESC
    if "--build" in sys.argv:                            # 2026-11-24 (A7C II port): the same sites in another build's files
        build_ogfile.use_build(sys.argv[sys.argv.index("--build") + 1])
        bo = build_ogfile
        BUILD, SUFFIX, CLIP_8K, CLIP_4K = bo.BUILD, bo.SUFFIX, bo.CLIP_8K, bo.CLIP_4K
        COMB, DESC, PROFILE_TABLES, UNIT_TABLE, CLIP = bo.COMB, bo.DESC, bo.PROFILE_TABLES, bo.UNIT_TABLE, bo.CLIP
        NDESC = bo.NDESC                                 # 2026-11-27: the FX2 has 691 descriptors (the A7 IV and A7C II 689)
    if "--rates" in sys.argv:                            # 2026-11-26 (Super 35 50p / 59.94p open gate): the descriptors of other coding-rate codes
        global RATES
        RATES = {c: RATE_CODE_NAMES[c] for c in (int(x) for x in sys.argv[sys.argv.index("--rates") + 1].split(","))}
    if "--raster" in sys.argv:                           # another picture size through the same sites; --name is then required
        i = sys.argv.index("--raster")
        W1, H1, NAME = int(sys.argv[i + 1]), int(sys.argv[i + 2]), sys.argv[sys.argv.index("--name") + 1]
        assert NAME != "ogfile57_v1" and W1 % 64 == 0 and H1 % 16 == 0 and 8847360 < W1 * H1 <= 33177600, "a two-core picture above the 4K class"
        WHY = sys.argv[sys.argv.index("--why") + 1] if "--why" in sys.argv else f"the owner asked for a {W1} by {H1} file (2026-11-20); this is its encoder side"
        GOES_WITH = sys.argv[sys.argv.index("--goes-with") + 1] if "--goes-with" in sys.argv else "the coprocessor designs of the same size"
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    sha = {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    keep = "--keep-level" in sys.argv
    r300 = "--rate300" in sys.argv                       # 2026-11-21: the 100M record settings at 300 Mbps (a test). The design gets its own name
    if r300:
        assert NAME.startswith("ogfile") and NAME.endswith("_v1")
        NAME = NAME[:-3] + "r300_v1"
    m1 = "--m1" in sys.argv                              # 2026-11-24: the 100M 4:2:2 10-bit setting at 23.98p with M = 1 (a test). Own name
    m1all = "--m1all" in sys.argv                        # 2026-11-24: M = 1 everywhere plus the edit-list start (after F981). Own name
    assert not (m1 and m1all), "--m1 or --m1all, not both"
    global ELST_VERSION
    ELST_VERSION = "v2" if "--v2" in sys.argv else "v3"
    global META
    META = "--meta" in sys.argv                          # 2026-11-24: the MP4 headers say the stream's size (with --m1all: v4 = v3 + these)
    assert not META or ("--m1all" in sys.argv and ELST_VERSION == "v3") or "--raster" in sys.argv, "--meta goes with --m1all (v3), making v4, or with --raster"
    if m1all and SUFFIX:                                 # 2026-11-25: the A7C II's v4 (its writer set-up's HEVC branch and m_vpcSt; ELST_BUILDS)
        global ELST_V3_SITE, ELST_V3_TABLE, ELST_V3_CODE, ELST_SITE
        # 2026-11-27: v3 (no --meta) as well, for the FX2's --no-meta fallback; the A7C II's designs are v4
        assert BUILD in ELST_BUILDS and ELST_VERSION == "v3" and (META or BUILD in SUFFIX_TEXTS), "--m1all on another build: v4 (--meta); v3 for the FX2"
        e = ELST_BUILDS[BUILD]
        ELST_V3_SITE, ELST_V3_TABLE, ELST_V3_CODE, ELST_SITE = e["site"], e["table"], e["code"], e["site"]
    if m1all:
        assert r300 and (not SUFFIX or BUILD in ELST_BUILDS) and "--raster" not in sys.argv, "--m1all is the A7 IV's (or A7C II's) 5760x3840 300 Mbps design only"
        NAME = NAME[:-3] + "m1_" + ("v4" if META else ELST_VERSION)
        WHY = ("the owner asked to fix the one-frame edit-list offset of the M = 1 test (F981) and to extend M = 1 to XAVC S (2026-11-24); the "
               "edit-list fix is global, so every descriptor of the design gets M = 1")
        GOES_WITH = "dmmwb4688_v1 + og57n_v1 (the real 5760x3840 picture) and og57cp_v3, all in coprocessor RAM, as ogfile57r300_v1"
    if m1:
        assert r300 and not SUFFIX and "--raster" not in sys.argv, "--m1 is a test on the A7 IV 5760x3840 300 Mbps design only"
        NAME = NAME[:-3] + "m1_v1"
        WHY = ("the owner asked for a test of trial 2 of 'Astra Analysis Check/5.7K cadence trials' (2026-11-24): duplicate frames at 5.7K; keep 4:2:2 "
               "and 300 Mbps and take the HEVC picture reordering out (M 3 -> 1) for the 100M 4:2:2 10-bit setting at 23.98p")
        GOES_WITH = "dmmwb4688_v1 + og57n_v1 (the real 5760x3840 picture) and og57cp_v3, all in coprocessor RAM, as ogfile57r300_v1"
    if SUFFIX:
        NAME = NAME[:-3] + SUFFIX + NAME[-3:]           # ogfile57r300_c2_v1, ogfile57r300m1_c2_v4
        if not m1all:
            WHY = "the owner asked for a 300 Mbps variant of the 5.7K state to test (2026-11-21); this is its encoder side"
        elif BUILD in SUFFIX_TEXTS:                      # 2026-11-27: the FX2's own words
            WHY = SUFFIX_TEXTS[BUILD]["why" if META else "why_v3"]
            GOES_WITH = SUFFIX_TEXTS[BUILD]["goes_with"]
        else:
            WHY = ("the owner asked for the A7 IV's metadata fix on the A7C II (2026-11-25): the A7 IV's 5.7K encoder step ogfile57r300m1_v4 (M = 1 "
                   "everywhere, the HEVC edit list at 0, the MP4 headers saying 5760x3840), on the A7C II's tables")
            GOES_WITH = "dmmwb4688_c2_v1 + og57n_c2_v1 (the real 5760x3840 picture) and og57cp_c2_v3, all in coprocessor RAM"
    d, picked, refs = build(lm, av, keep, r300, m1, m1all)
    if keep:
        d.name += "_l5"
    by, kinds = {}, {}
    for p in d.patches:
        by.setdefault(p["binary"], []).append(p)
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    out = {"design": d.name, "title": d.title, "generated_by": "build/build_og57.py" + (" --keep-level" if keep else "") + (f" --build {BUILD}" if SUFFIX else ""),
           "family": "hs_s", **({"build": BUILD} if SUFFIX else {}),
           "format": "XAVC HS 4K (HEVC) and XAVC S 4K (AVC)", "raster": [W1, H1], "rates": sorted(RATES.values()),
           "goes_with": GOES_WITH,
           "artifact_sha256": sha,
           "summary": {b: {"sites": len(ps), "bytes": sum(len(p["new"]) // 2 for p in ps), "code_sites": sum(p["code"] for p in ps)} for b, ps in by.items()},
           "sites_by_kind": kinds, "level": "the stock level bytes are kept" if keep else "Level 6 (HEVC 180, AVC 60)" + ("; Level 6.1 (183, 61) in the 300 Mbps profiles" if r300 else ""),
           "encoder_cores": "both (UseCore 2), as every stock descriptor above 249 million pixels a second",
           "memory_blocks_row_3": {"order": ["frame buffer CD", "frame buffer LD", "multi buffer", "ES buffer"], "ids": [hex(i) for i in UNIT_ROW]},
           "rule_checked_against_sonys_own_two_core_profiles": refs,
           "while_applied": ["the formats' other frame rates find no descriptor: their recordings are refused at encoder open",
                             "other formats are not touched", "the container and the metadata still say 3840 by 2160",
                             "the bit rate is the one the menu's record setting says" if not r300 else
                             "the 100M record settings (and any higher one of these formats) record at 300 Mbps; the lower settings keep their bit rate; the menu, "
                             "the remaining-time figure and the container's own bit-rate fields still say what the setting says"],
           "descriptors": picked, "patches": d.patches, "optional_sites": []}
    if r300:
        out["generated_by"] += " --rate300"
        out["bit_rate_300"] = {"what": "three fields of each profile at 97 million or above: bit rate, highest bit rate, stream buffer (bits). Named by their values; the "
                                       "code that reads them was not traced field by field", "profiles": RATE_ROWS}
    if m1:
        out["generated_by"] += " --m1"
        out["title"] += "; the 100M 4:2:2 10-bit setting of XAVC HS 4K at 23.98p with I and P pictures only (M = 1)"
        out["while_applied"].append("XAVC HS 4K, 24p (23.98p), 100M 4:2:2 10-bit records with M = 1: I and P pictures only, no B pictures, no picture reordering; "
                                    "every other setting keeps M = 3 (the control in the same state)")
        out["prediction_m1"] = {
            "what": "descriptor PredMode (+0x85, sent at channel creation) and profile MParam (+0x97, copied to EncConfig +0x18 by the start-block builder "
                    "0xffffffc0012174c0, HEVC branch; also read by the stream-info getter 0xffffffc00121b444) from 3 to 1",
            "sites": M1_ROWS, **M1_INFO,
            "source": "trial 2 of Astra Analysis Check/5.7K cadence trials/README.md (ogfile57r300_m1_2398_trial.json); offsets checked against it",
            "expected": "codec multi buffer 25,559,040 -> 12,845,056 bytes, reference pictures 88,506,368 bytes unchanged (build/emu_vcd_chmem.py); "
                        "start block differs from ogfile57r300_v1 at EncConfig +0x18 only (build/run_og57_emu.py)"}
    if m1all:
        out["generated_by"] += " --m1all"
        out["title"] += "; every record setting with I and P pictures only (M = 1), and the MP4 edit list starting at 0"
        out["while_applied"].append("every record setting of XAVC HS 4K and XAVC S 4K at 23.98p and 25p records with M = 1: I and P pictures only, "
                                    "no B pictures, no picture reordering")
        if ELST_VERSION == "v2":
            out["while_applied"].append("every MP4 the recorder writes has a video edit list starting at 0 (libmpr.so 0x118004); right for M = 1 streams. "
                                        "A stream with B pictures (proxy or any other format, if one records) would show its first picture one frame late")
            out["prediction_m1"] = {
                "what": "every descriptor of the design: PredMode +0x85 and the profile's MParam (HEVC +0x97, AVC +0x9b) 3 -> 1; libmpr.so 0x118004: the "
                        "video edit list's start 1 frame -> 0",
                "sites": M1_ROWS, **M1_INFO,
                "source": "F980 (the one-setting test), F981 (it removed the held frames; the edit list hid the first picture)"}
            out["libmpr_code_guards"] = [{"site": hex(ELST_SITE), "guards": [{"file_off": hex(ELST_CODE[0][0]), "bytes": lm[ELST_CODE[0][0]:ELST_SITE].hex()},
                                                                             {"file_off": hex(ELST_SITE + 4), "bytes": lm[ELST_SITE + 4:ELST_CODE[-1][0] + 4].hex()}]}]
        else:
            out["while_applied"].append("an HEVC MP4 recorded normally has a video edit list starting at 0 (libmpr.so 0x11f4e0); right for M = 1 HEVC. "
                                        "AVC keeps its one-frame start, which its constant one-frame composition offset needs (C0557). An HEVC stream "
                                        "with B pictures would show its first picture one frame late")
            out["prediction_m1"] = {
                "what": "every descriptor of the design: PredMode +0x85 and the profile's MParam (HEVC +0x97, AVC +0x9b) 3 -> 1; libmpr.so 0x11f4e0 (writer "
                        "set-up of a normal recording, HEVC branch): the video edit list's start 1 frame -> 0",
                "sites": M1_ROWS, **M1_INFO,
                "source": "F980, F981, F982; F986 (v2 on the camera: no held frames in XAVC HS and XAVC S, but 0x118004 did not reach the edit list)",
                "replaces": "ogfile57r300m1_v2: the same av-cam sites; its libmpr.so site 0x118004 is not used by a normal recording"}
            a, b = ELST_V3_CODE[0][0][0], ELST_V3_SITE                 # 0x11f4cc .. the site: 20 bytes, as guards of at most 16
            g = [{"file_off": hex(x), "bytes": lm[x:min(x + 16, b)].hex()} for x in range(a, b, 16)]
            g.append({"file_off": hex(b + 4), "bytes": lm[b + 4:b + 8].hex()})                                  # str w0, [x29, #0xb40]
            avc = ELST_V3_CODE[1]
            g.append({"file_off": hex(avc[0][0]), "bytes": lm[avc[0][0]:avc[-1][0] + 4].hex()})                # the AVC branch, which must stay
            for comb in (5, 7):                                                                                  # m_vpcSt rows of the HEVC formats
                r = ELST_V3_TABLE + 0x1C * comb
                g.append({"file_off": hex(r), "bytes": lm[r:r + 8].hex()})
                g.append({"file_off": hex(r + 0x14), "bytes": lm[r + 0x14:r + 0x1C].hex()})
            out["libmpr_code_guards"] = [{"site": hex(b), "guards": g}]
            if META:
                out["generated_by"] += " --meta"
                out["title"] += "; the MP4 headers (tkhd, stsd, PROF) say %dx%d" % (W1, H1)
                out["mp4_meta"] = {"what": "the track config 0x222b18 builds (tkhd, stsd and Sony's PROF video entry) says the stream's size; Sony's XML "
                                           "(NonRealTimeMeta) is unchanged: its size keys the videoCodec name lookup", **META_INFO,
                                   "checked": "build/emu_mp4_meta.py -> evidence/pipeline/mp4_meta_emu.json" if not SUFFIX else
                                              SUFFIX_TEXTS[BUILD]["checked"] if BUILD in SUFFIX_TEXTS else
                                              "build/emu_mp4_meta.py --build %s -> evidence/a7c2/mp4_meta_emu_c2.json" % BUILD}
                taken = {int(e["site"], 16) for e in out["libmpr_code_guards"]} | {int(s["file_off"], 16) for s in META_INFO["sites"]}
                g0 = [x for x in META_INFO["guards"] if not any(abs(int(x["file_off"], 16) - int(y["file_off"], 16)) < 4 for y in g)]
                assert not any(int(x["file_off"], 16) in taken for x in g0)
                out["libmpr_code_guards"] += [{"site": s["file_off"], "guards": g0 if k == 0 else []} for k, s in enumerate(META_INFO["sites"])]
                out["while_applied"].append("the MP4 headers of XAVC HS 4K and XAVC S 4K files say %dx%d (3:2); Sony's XML in the file still "
                                            "says 3840x2160, 16:9" % (W1, H1))
    if "--rates" in sys.argv:
        out["generated_by"] += " --rates " + sys.argv[sys.argv.index("--rates") + 1]
        out["while_applied"][0] = ("only these coding rates are set up: " + ", ".join(RATES[c] for c in sorted(RATES)) + "; the formats' other frame rates "
                                   "keep their 3840 by 2160 descriptors while the encoder request says %d by %d: do not record them" % (W1, H1))
    if META and not m1all:                               # 2026-11-26: the MP4 header sizes on a --raster design (the sites and guards of --m1all --meta)
        out["generated_by"] += " --meta"
        out["title"] += "; the MP4 headers (tkhd, stsd, PROF) say %dx%d" % (W1, H1)
        out["mp4_meta"] = {"what": "the track config 0x222b18 builds (tkhd, stsd and Sony's PROF video entry) says the stream's size; Sony's XML "
                                   "(NonRealTimeMeta) is unchanged", **META_INFO, "checked": "build/mp4_meta_sites.check on the stock libmpr.so"}
        out["libmpr_code_guards"] = [{"site": s_["file_off"], "guards": META_INFO["guards"] if k == 0 else []} for k, s_ in enumerate(META_INFO["sites"])]
        out["while_applied"].append("the MP4 headers of XAVC HS 4K and XAVC S 4K files say %dx%d; Sony's XML in the file still says 3840x2160, 16:9" % (W1, H1))
    out_dir = ROOT / "modding" / "designs"
    (out_dir / f"{d.name}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    for b, ps in by.items():
        (out_dir / f"{d.name}_pokes_{b.split('.')[0].replace('-', '')}.txt").write_text("".join(f"{p['file_off']} {p['new']}\n" for p in ps), encoding="utf8", newline="\n")
    print(d.name, out["summary"], kinds, "descriptors:", len(picked), "profiles:", len({p["profile_key"] for p in picked}))
    for fam, rs in refs.items():
        for r in rs:
            print("   reference", fam, r)
    if "--list" in sys.argv:
        for p in picked:
            print("    #%d %s %s %s class %d key %d level %s" % (p["descriptor"], p["family"], p["format"], p["rate"], p["quality_class"], p["profile_key"], p.get("level_byte")))
    if "--register" in sys.argv:
        import records
        st = records.Store()
        st.begin("design %s: the encoder side of a %d by %d file on the stock 4K formats, as patch sites" % (d.name, W1, H1), WHY,
                 evidence="modding/designs/%s.json from build/build_og57.py" % d.name, author="build_og57.py")
        for i, p in enumerate(d.patches, 1):
            data = {"design": d.name, "design_title": d.title, "artifact": p["binary"], "artifact_sha256": sha[p["binary"]], "addr": p["va"], "file_off": p["file_off"],
                    "length": len(p["new"]) // 2, "old_hex": p["old"], "old_source": "stock file", "new_hex": p["new"], "patch_kind": p["kind"], "risk_class": "R2",
                    "old_verified": True, "note": p["note"], "source": f"modding/designs/{d.name}.json"}
            rid, ttl = f"PS-{d.name}-{i}", f"{d.name} {p['kind']}: {p['note']}"
            if rid in st.records:
                st.amend(rid, data, title=ttl)
            else:
                st.add("patch_site", ttl, data, id=rid, level="static", certainty="inferred", build="a7iv_602", subsystem="patch-design")
        print("registered:", st.commit(), "changes")


if __name__ == "__main__":
    main()
