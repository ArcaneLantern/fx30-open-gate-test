"""Write fx30_expected.h for fx30read.c from the FX30 6.01 files and the port designs (FX30 port, 2026-11-26).

  C:\\Python313\\python.exe -B gen_fx30.py

helper_fx2/gen_fx2.py with this build's files, designs and addresses (modding/FX30_PORT.md). Everything the helper compares against is taken
here from the extracted 6.01 update and from modding/designs/{ogsq_fx30_v2, outsz2560_fx30_v1, ogfile2560_hs_s_fx30_v2, lcd32dsq_fx30_v1}.json
(and avdec8k_fx30_v1 for the optional playback step, whose av-cam sites the check reports). The helper holds no other constant about the
camera except the addresses listed at the top of this file.
  - A site may carry a second target (TARGET-B): the sensor design's variant B, ogsq_fx30_v2b (the LC and read-out spans and the stored
    records differ from ogsq_fx30_v2 in two values each; an A/B test).
  - The sensor design's 9 table/record sites are hard sites (stock or target, counted). One of them, sensor_window, is the register
    matrix's rows of the sensor's window registers (v2; fx30read_v1 did not look at them and design v1 did not write them).
  - The five stored drive-parameter records are soft sites: the camera computes them at start-up (NTSC or PAL table) and keeps run-time
    bytes in them, so they need not equal the emulated ones; the check prints their bytes and the PC reads the design offsets.
  - The output-size words are soft (zero until a movie mode has run), the screen words soft (the screen step is optional).
Also writes fx30_expected.json (what the PC checks against) and fx30_reference.json (what the PC needs to read a dump). Read-only on the inputs.

  C:\\Python313\\python.exe -B gen_fx30.py --57      (2026-11-28) the 5.7K twin: fx30_expected57.h / .json and fx30_reference57.json, with the 5.7K designs
  as the targets (og57n_fx30_v1, og57cp_fx30_v1, ogfile57r300m1_fx30_v4). The same source builds a second pair of libraries from it (build_fx30.sh
  check57 | dump57), so a camera in the 5.7K state reads as READY; the ordinary pair calls its records and encoder sites OTHER. No variant-B
  alternates there (the 5.7K state uses the default sensor cells).
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EX = ROOT / "work/extracted/fx30_601/0700_part_image/dev"
DES = ROOT / "modding/designs"
sys.path.insert(0, str(ROOT / "build"))

BASE = 0x108000
K57 = "--57" in sys.argv
LABEL = "fx30read_v2 5.7K" if K57 else "fx30read_v2"
SUF = "57" if K57 else ""
CP_LO, CP_HI = 0xC0000, 0x2700000                     # coprocessor addresses a read may have: its logs, image and RAM tables
AVCAM_PHYS, AVCAM_RESERVE = 0x401000000, "@0x401000000"   # kemco: memrsv=0x01000000@0x401000000:ex, as the FX3 (FX30_PORT_ENCODER.md)
ID_FILES = {"/libmpr.so": "nflasha15/lib/libmpr.so", "/libsencore.so": "nflasha15/lib/libsencore.so", "/libJiritsu.so": "nflasha15/lib/libJiritsu.so"}
# four 4 KB pages of coprocessor CODE that no design touches: a low code page, the record selector's (0x73ccde), the movie size table's
# set-up (0x4644bc) and the drive-parameter table map (constructor caller 0x8e7826); each differs from every other kit's body
ID_PAGES = (0x128000, 0x73C000, 0x464000, 0x8E7000)
# The FX30 sensor's register matrix: 154 rows of 20 bytes (the address of the register's value in the shadow, then one byte per column,
# 14 columns, 2 spare) and a zero row, then the column map (31 words, one per drive mode). The firmware walks it from 0x1038d1c
# (0x8e8218; build/emu_sensor_regs_fx30.py). fx30read_v1 had 0x1038e48 / 139 rows and so missed the first 15: the window registers.
# The shadow is 4-byte entries {u16 register, u16 value} from 0x1123de4.
MATRIX, MATRIX_ROWS, MROW, COLMAP, IDS, NMODES = 0x1038D1C, 154, 20, 0x1039938, 0xD10D68, 31
SHADOW0 = 0x1123DE4
RECS, REC = 0x20D93A4, 0x160
SIZE_TABLE = 0x155D40C
DESIGNS = ("ogsq_fx30_v2", "outsz2560_fx30_v1", "ogfile2560_hs_s_fx30_v2", "lcd32dsq_fx30_v1", "avdec8k_fx30_v1")
VARIANT_B = "ogsq_fx30_v2b"
if K57:
    DESIGNS = ("og57n_fx30_v1", "og57cp_fx30_v1", "ogfile57r300m1_fx30_v4", "lcd32dsq_fx30_v1", "avdec8k_fx30_v1")
UNIT, DESC, DSIZE, CLIP, NDESC = 0x3926B8, 0x392758, 0x90, 0x39061C, 689    # build_ogfile.OTHER_BUILDS["fx30_601"] (FX30_PORT_ENCODER.md)
# The pages the dump reads beyond the display pages (taken from the screen design's sites and guards below, one page each):
DUMP_FIXED = (("shadow", 0x1123000, 2), ("matrix", 0x1038000, 2), ("sizetable", 0x155D000, 1), ("records", 0x20D9000, 3),
              ("kprint", 0xE0000, 32), ("bootlog", 0xC0000, 8),
              # the resize module (A7 IV 0x1450000 + 3 pages: result 0x145091c, drive-parameter copy 0x1450bc4, settings 0x1452488; the FX30's
              # settings are 0x1573a30 (build/emu_rc_fit_fx30.py), the same distance back gives 0x1571ec4 for the result, not confirmed: the
              # dump decoder searches these pages for known sizes) and the resize working structure (A7 IV 0x11e1510, FX30 0x12ddef8)
              ("resizestate", 0x1571000, 3), ("resizework", 0x12DD000, 1),
              # the panel records: rear panel type byte 0x16295d4 (2 = 4:3, 3 = 3:2), second output 0x1629704 (build/build_lcd_fx30.py)
              ("paneltype", 0x1629000, 1))


def c_bytes(b):
    return "{" + ",".join(str(x) for x in b) + "}"


def design(n):
    return json.loads((DES / f"{n}.json").read_text(encoding="utf8"))


def main():
    cp = (EX / "nflasha8/cpapp-b.bin").read_bytes()
    av = (EX / "nflasha3/av-cam.bin").read_bytes()
    lm = (EX / "nflasha15/lib/libmpr.so").read_bytes()
    og, oz, fl, sc, ad = (design(n) for n in DESIGNS)
    sha_cp = hashlib.sha256(cp).hexdigest()
    assert og["artifact_sha256"] == sha_cp and og["build"] == "fx30_601"
    assert fl["artifact_sha256"] == {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    assert ad["artifact_sha256"] == hashlib.sha256(av).hexdigest()
    out, blobs = [], []

    def blob(b):
        blobs.append(f"static const unsigned char B{len(blobs)}[] = {c_bytes(b)};")
        return f"B{len(blobs) - 1}"

    out.append(f'#define FX30_LABEL "{LABEL}"\n#define CP_LO {CP_LO:#x}U\n#define CP_HI {CP_HI:#x}U\n#define AVCAM_PHYS {AVCAM_PHYS:#x}UL\n'
               f'#define AVCAM_RESERVE "{AVCAM_RESERVE}"')
    out.append("struct id_file { const char *name; unsigned char sha256[32]; };\nstruct id_page { unsigned int address; unsigned char sha256[32]; };\n"
               "struct cp_site { const char *name; unsigned int address, length; const unsigned char *stock, *target; int soft; const unsigned char *alt; };\n"
               + ("/* packed: a library is one upload packet (65,520 bytes at most) and the 5.7K designs have 310 encoder-side sites; a site's stock\n"
                  "   bytes are at mp_blob[at], its target bytes right after them. No pointers: nothing to relocate. */\n"
                  "struct mp_site { unsigned int offset; unsigned short at; unsigned char length; };\n"
                  "#define MP_STOCK(e) (mp_blob + (e)->at)\n#define MP_TARGET(e) (mp_blob + (e)->at + (e)->length)\n" if K57 else
                  "struct mp_site { unsigned long offset; unsigned int length; const unsigned char *stock, *target; };\n"
                  "#define MP_STOCK(e) ((e)->stock)\n#define MP_TARGET(e) ((e)->target)\n") +
               "struct av_guard { const char *name; unsigned long offset; unsigned int length; unsigned char sha256[32]; };\n"
               "struct dump_range { const char *name; unsigned int address, pages; };")
    rows = [f'    {{"{n}", {c_bytes(hashlib.sha256((EX / p).read_bytes()).digest())}}},' for n, p in ID_FILES.items()]
    out.append("static const struct id_file id_files[] = {\n" + "\n".join(rows) + "\n};")
    # ---- coprocessor sites
    sites, alt = [], {}                                   # alt: site name -> variant B's bytes where they differ from the design's
    ogb = design(VARIANT_B)
    assert ogb["artifact_sha256"] == sha_cp and [p["addr"] for p in ogb["patches"]] == [p["addr"] for p in og["patches"]]
    assert all(a["old"] == b["old"] for a, b in zip(og["patches"], ogb["patches"])) and ogb["summary"]["sensor"] == og["summary"]["sensor"]
    newb = {p["addr"]: bytes.fromhex(p["new"]) for p in ogb["patches"]}
    names = {"crop": "crop", "stream-0": "window", "stream-1": "pdaf", "LC": "lc", "read-out": "readout", "geometry": "geometry",
             "register matrix": "sensor_window"}
    for p in og["patches"]:
        a, old, new = int(p["addr"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert cp[a - BASE:a - BASE + len(old)] == old and len(old) == len(new)
        if p["kind"] == "S":
            name = next(v for k, v in names.items() if p["note"].startswith(k))
        else:
            name = "record_left" if "left" in p["note"] else "record_right"
        sites.append((name, a, old, new, 0))
        if newb[p["addr"]] != new and not K57:
            alt[name] = newb[p["addr"]]
    ids = list(struct.unpack_from("<%dI" % NMODES, cp, IDS - BASE))
    for m, sr in og["stored_records"].items():            # soft: computed at start-up, run-time bytes; the PC reads the design offsets
        assert sr["index"] == ids.index(int(m, 16))
        sites.append((f"stored_record_{m}", RECS + sr["index"] * REC, bytes.fromhex(sr["ntsc"]["stock"]), bytes.fromhex(sr["ntsc"]["design"]), 1))
        srb = ogb["stored_records"][m]
        assert srb["index"] == sr["index"] and srb["offsets_that_differ"] == sr["offsets_that_differ"] and srb["ntsc"]["stock"] == sr["ntsc"]["stock"]
        if not K57:
            alt[f"stored_record_{m}"] = bytes.fromhex(srb["ntsc"]["design"])
    for k, s in enumerate(oz["sites"]):                   # soft: the size table is zero until a movie mode has run (5.7K: five words, the last the size)
        sites.append(("outsize" if len(oz["sites"]) == 1 else f"outsize{k}", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))
    for k, g in enumerate(oz["guards"]):
        sites.append((f"outsize_guard{k}", int(g["ram_address"], 16), bytes.fromhex(g["bytes"]), None, 1))
    for k, s in enumerate(sc["sites"]):                   # soft: the screen step is optional (apply --no-screen); reported, not counted
        a, old = int(s["ram_address"], 16), bytes.fromhex(s["old"])
        if BASE <= a < BASE + len(cp):
            assert cp[a - BASE:a - BASE + 4] == old
        sites.append((f"screen{k}", a, old, bytes.fromhex(s["new"]), 1))
    pages = {x & ~0xFFF for _, a, o, _, _ in sites for x in (a, a + len(o) - 1) if a < BASE + len(cp)}
    assert not any(p in pages for p in ID_PAGES), "an identity page holds a design site"
    rows = [f"    {{{a:#x}, {c_bytes(hashlib.sha256(cp[a - BASE:a - BASE + 4096]).digest())}}}," for a in ID_PAGES]
    out.append("static const struct id_page id_pages[] = {\n" + "\n".join(rows) + "\n};")
    rows = []
    for name, a, old, new, soft in sites:
        assert CP_LO <= a and a + len(old) <= CP_HI and len(old) <= 3072
        rows.append(f'    {{"{name}", {a:#x}, {len(old)}, {blob(old)}, {blob(new) if new is not None else "0"}, {soft}, {blob(alt[name]) if name in alt else "0"}}},')
    out.append("static const struct cp_site cp_sites[] = {\n" + "\n".join(rows) + "\n};")
    # ---- main-processor sites: the encoder side (hard), then the optional playback step's av-cam words (their own state, see below)
    lmr, avr, av_hi, mpblob = [], [], 0, bytearray()
    for p in fl["patches"]:
        o, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = lm if p["binary"] == "libmpr.so" else av
        assert src[o:o + len(old)] == old
        if K57:
            (lmr if p["binary"] == "libmpr.so" else avr).append(f"    {{{o:#x}U, {len(mpblob)}, {len(old)}}},")
            mpblob += old + new
            assert len(mpblob) < 0x10000 and len(old) < 256 and o < 1 << 32
        else:
            (lmr if p["binary"] == "libmpr.so" else avr).append(f"    {{{o:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}},")
        if p["binary"] == "av-cam.bin":
            av_hi = max(av_hi, o + len(old))
    if K57:
        out.append("static const unsigned char mp_blob[] = " + c_bytes(mpblob) + ";")
    out.append("static const struct mp_site lm_sites[] = {\n" + "\n".join(lmr) + "\n};")
    out.append("static const struct mp_site av_sites[] = {\n" + "\n".join(avr) + "\n};")
    spans = [(int(p["file_off"], 16), len(p["old"]) // 2) for p in fl["patches"] if p["binary"] == "av-cam.bin"]
    free = lambda k: all(DESC + DSIZE * (k + 4) <= so or so + sn <= DESC + DSIZE * k for so, sn in spans)
    d0 = next(k for k in range(NDESC - 4) if free(k))
    # the 5.7K encoder design rewrites clip-format row 3 (the unused 8192x4320 row): its guard is rows 4 to 7
    clip_guard = ("clip_rows_4_7", CLIP + 0x40, 0x40) if K57 else ("clip_rows_2_7", CLIP + 0x20, 0x60)
    guards = (("unit_rows_0_2", UNIT, 0x30), clip_guard, (f"descriptors_{d0}_{d0 + 3}", DESC + DSIZE * d0, 4 * DSIZE))
    rows = []
    for name, o, n in guards:
        assert all(o + n <= so or so + sn <= o for so, sn in spans), name
        rows.append(f'    {{"{name}", {o:#x}UL, {n}, {c_bytes(hashlib.sha256(av[o:o + n]).digest())}}},')
        av_hi = max(av_hi, o + n)
    out.append("static const struct av_guard av_guards[] = {\n" + "\n".join(rows) + "\n};")
    av_lo = min([so for so, _ in spans] + [o for _, o, _ in guards]) & ~0xFFF
    out.append(f"#define AV_LO {av_lo:#x}UL\n#define AV_HI {av_hi:#x}UL")
    # the dump's display pages: every page holding a screen site or guard
    disp_pages = sorted({int(x["ram_address"], 16) & ~0xFFF for x in sc["sites"] + sc["guards"]})
    dump_ranges = list(DUMP_FIXED) + [(f"display{k}", p, 1) for k, p in enumerate(disp_pages) if not any(a <= p < a + 4096 * n for _, a, n in DUMP_FIXED)]
    rows = [f'    {{"{n}", {a:#x}, {k}}},' for n, a, k in dump_ranges]
    assert all(CP_LO <= a and a + 4096 * k <= CP_HI for _, a, k in dump_ranges)
    starts = sorted((a, a + 4096 * k) for _, a, k in dump_ranges)
    assert all(e <= s for (_, e), (s, _) in zip(starts, starts[1:])), "two dump ranges overlap"
    out.append("#if DUMP\nstatic const struct dump_range dump_ranges[] = {\n" + "\n".join(rows) + "\n};\n#endif")
    text = ("/* Generated by gen_fx30.py from the FX30 6.01 files and the port designs. Do not edit. */\n#ifndef DUMP\n#define DUMP 0\n#endif\n"
            + "\n".join(blobs) + "\n" + "\n".join(out) + "\n")
    (HERE / f"fx30_expected{SUF}.h").write_text(text, encoding="utf8", newline="\n")
    facts = {"label": LABEL, "cp_lo": CP_LO, "cp_hi": CP_HI, "avcam_phys": AVCAM_PHYS, "avcam_reserve": AVCAM_RESERVE,
             "id_files": {n: hashlib.sha256((EX / p).read_bytes()).hexdigest() for n, p in ID_FILES.items()},
             "id_pages": {hex(a): hashlib.sha256(cp[a - BASE:a - BASE + 4096]).hexdigest() for a in ID_PAGES},
             "cp_sites": [{"name": n, "address": hex(a), "length": len(o), "soft": s} for n, a, o, _, s in sites],
             "variant_b_sites": sorted(alt),
             "lm_sites": len(lmr), "av_sites": len(avr), "av_guards": [g[0] for g in guards], "dump_ranges": [[n, hex(a), k] for n, a, k in dump_ranges],
             "designs": {d["design"]: hashlib.sha256((DES / (d["design"] + ".json")).read_bytes()).hexdigest() for d in (og, ogb, oz, fl, sc, ad)}}
    (HERE / f"fx30_expected{SUF}.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf8", newline="\n")
    # ---- what the PC needs to read a dump without the firmware files
    matrix = []
    for k in range(MATRIX_ROWS):
        a = struct.unpack_from("<I", cp, MATRIX - BASE + MROW * k)[0]
        assert 0x1123000 <= a < 0x1125000 and (a - SHADOW0) % 4 == 2
        matrix.append([a, cp[MATRIX - BASE + MROW * k + 4:MATRIX - BASE + MROW * k + MROW].hex(), struct.unpack_from("<H", cp, a - 2 - BASE)[0]])
    assert len({m[2] for m in matrix}) == MATRIX_ROWS and cp[MATRIX - 4 - BASE:MATRIX - BASE] == bytes(4)
    sensor = og["summary"]["sensor"]
    assert int(sensor["matrix"], 16) == MATRIX and sensor["matrix_rows"] == MATRIX_ROWS and int(sensor["shadow_base"], 16) == SHADOW0
    assert not any(cp[MATRIX - BASE + MROW * MATRIX_ROWS:MATRIX - BASE + MROW * (MATRIX_ROWS + 1)]) and MATRIX + MROW * (MATRIX_ROWS + 1) == COLMAP
    emu = json.loads((ROOT / "evidence/fx30/sensor/drvparam_stock_fx30_601.json").read_text(encoding="utf8"))["modes"]
    ref = {"about": "FX30 6.01 reference data for reading an fx30read dump; from cpapp-b.bin and build/emu_drvparam.py fx30_601", "matrix_address": hex(MATRIX),
           "matrix_row_bytes": MROW, "matrix_columns": 14, "matrix": matrix, "column_map": list(struct.unpack_from("<%dI" % NMODES, cp, COLMAP - BASE)),
           "mode_ids": [hex(x) for x in ids], "records_address": hex(RECS), "record_size": REC,
           "emulated_stock_records": {m: v["record"] for m, v in emu.items()}, "size_table_address": hex(SIZE_TABLE),
           "stored_records_design": og["stored_records"], "open_gate_column": 1,
           # variant B of the sensor design (ogsq_fx30_v2b): the same sites; two values differ (first phase-detect row, read-out length)
           "stored_records_design_b": ogb["stored_records"],
           "variant_b": {"design": ogb["design"], "first_pdaf_row": [og["summary"]["pdaf"]["first_pdaf_row"], ogb["summary"]["pdaf"]["first_pdaf_row"]],
                         "readout_length": [og["summary"]["pdaf"]["readout_length"], ogb["summary"]["pdaf"]["readout_length"]]},
           # the sensor's own window: registers 6/7 = window row + row_bias, 8/9 = (rows + margins) / 2 line pairs, 14 = first phase-detect
           # block, 16 = phase-detect rows / 2, 25 = read-out f2; [stock, design] per register; cells = the matrix bytes of column 1
           "sensor_window": {"registers": sensor["registers"], "row_bias": sensor["row_bias"], "margins": sensor["margins"],
                             "cells": sensor["cells"], "column": sensor["column"], "sensor_design": og["design"]},
           "window": {"stock_row": 406, "stock_height": 3348, "design_row": og["summary"]["window_row"], "design_height": og["summary"]["window"][1],
                      "record_offsets": {"height": "0x66", "pdaf_rows": "0x8c", "row": "0xf6", "row_copy": "0x102", "first_block": "0x10e",
                                         "readout_length": "0x142", "first_pdaf_row": "0x15a", "sampling_ratio": "0x6"}},
           "screen_words": [{"address": s["ram_address"], "stock": s["old"], "new": s["new"], "note": s.get("note", "")} for s in sc["sites"]],
           "screen_design": sc["design"],
           "panel_type": {"rear": "0x16295d4", "second": "0x1629704", "codes": {"1": "16:9", "2": "4:3", "3": "3:2"}},
           "ram": {"resize_result_predicted": "0x1571ec4 (A7 IV 0x145091c, not confirmed: the dump decoder searches 0x1571000.. for known sizes)",
                   "resize_settings": "0x1573a30", "resize_work": "0x12ddef8", "shadow_base": hex(SHADOW0)}}
    assert len(ref["emulated_stock_records"]) == NMODES
    if K57:
        ref.pop("stored_records_design_b"), ref.pop("variant_b")
        ref["state"] = {"name": "5.7K", "front_end": og["summary"]["front_end"], "output": oz["summary"]["output_size"], "designs": list(DESIGNS[:3])}
    (HERE / f"fx30_reference{SUF}.json").write_text(json.dumps(ref) + "\n", encoding="utf8", newline="\n")
    print(f"fx30_expected{SUF}.h: {len(sites)} coprocessor sites ({len(sc['sites'])} of the screen, 5 stored records), "
          f"{len(lmr)} libmpr sites, {len(avr)} av-cam sites, {len(dump_ranges)} dump ranges, {len(text)} bytes of header")


if __name__ == "__main__":
    main()
