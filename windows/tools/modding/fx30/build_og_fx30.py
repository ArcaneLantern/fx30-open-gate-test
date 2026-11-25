"""FX30 6.01 (fx30_601) open gate, sensor and first-stage side: design ogsq_fx30_v1 (FX30 port, 2026-11-26).

  C:\\Python313\\python.exe -B build\\build_og_fx30.py            (needs Unicorn and capstone: C:\\Python313 has them)

writes modding/designs/ogsq_fx30_v1.json and evidence/fx30/sensor/*.json. Nothing is written to a firmware file or sent to a camera.

What the FX30 does in 4K 16:9 (read from cpapp-b.bin 6.01, every fact asserted below):
  - 31 drive modes (ids 0xd10d68). 0x820, 0x880, 0x890, 0x8c0, 0x8d0 (indices 2, 4, 5, 6, 7) read the same 5952 x 3348 window ("6K") at
    sensor row 406: their crop, stream-0, stream-1 (phase detect), LC and read-out rows are equal, and all five use register-matrix column 1
    (column map 0x1039938). They differ only in timing: 0x8c0 = 23.98p (60 Hz table) / 24.00p (50 Hz), 0x820/0x880 = 29.97p / 25p, and
    0x890/0x8d0 are the same rates at line length 360 instead of 340.
  - The record selector 0x73ccde gives all five the same picture-record pair 0xc79440 / 0xc79ff8 (frame 5976 x 3356, crop 5952 x 3348).
  - The register matrix (0x1038e48, 139 rows of 20 bytes, 14 columns) holds no window: columns 1 (5952 x 3348), 2 (5612 x 3156), 8 (4648 x 2616)
    and 9 (5952 x 3140) are byte-identical. The window comes from the per-mode tables through the stored drive-parameter record.
So the open gate keeps the 4K mode's own sensor set-up and line timing and only makes the window taller: 5952 x 3968 (3:2) from row 96, which
centres it where the 16:9 window is centred (row 2080). It is read two rows per line period like the stock window: about 1,990 of the 4,410
line periods of a 24p frame.

The cells (each of the five modes' rows; the rules are read off the FX30's own movie modes, which all obey them):
  geometry 0xcb57a8.. (12-byte rows by mode id) +10   window row (406)                     -> 96
  crop     0xd10de4 (20-byte rows) +6                 window row (406)                     -> 96
           +18                                        first phase-detect block k (9)       -> 2     (LC +12 = 25 + 48 k in every movie mode)
  stream-0 0xe0278a (38) +26                          window height (3348)                 -> 3968
  stream-1 0xe02c24 (38) +26                          phase-detect rows p (68)             -> 82
  LC       0xe030be (14) +8                           window row (406)                     -> 96
           +12                                        first phase-detect row (457)         -> 121
  read-out 0xe03270 (14) +4                           f2, line pairs ahead of the picture (41) -> 48   (2 f2 = p + 14 in every line-340 movie mode)
           +12                                        read-out length in line periods (1704) -> 2014 ((rows + 12) / 2 + 24, as stock)
Phase-detect rows sit at sensor rows 25 + 48 j. The rows a window carries were fitted on the four movie windows (406/3348, 510/3140,
502/3156, 770/2616); row 96 is chosen so that the new window's first and last block lie well inside every margin those four allow (blocks
j = 2..83: p = 82).

The picture records: a row model fitted on the FX30's three stock pairs of the same family (0xc79440 3356 rows, 0xc76560 3148 rows (DCI),
0xc7abb0 3164 rows) -- each field that follows the stage rows does so as +rows, +rows/2, +rows/4, +p or +2 f2 (+0x95e is the window row) --
then the column geometry and every register word from build/build_fhnative.assemble (the firmware's planner and packers, which rebuild every
stock FX30 pair exactly). Self-test: the 3356-row pair is rebuilt from the 3148-row DCI pair and the DCI pair from the 3356-row pair, byte for byte.
The Lrc squeezes 5952 x 3968 into the stock 4336 x 2438 front end; with the vertical sampling ratio 27/32 in each stored record (5952 x 3968 x
27/32 = 5952 x 3348, 16:9) the resize fit keeps every row (the A7 IV's ogsq_v3, F681/F682), and the output-size step makes the file 3840 x 2560.
"""
import hashlib
import json
import struct
import sys
from fractions import Fraction as Fr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402
import build_fhstage as F  # noqa: E402
import build_fhnative as N  # noqa: E402
import lint_split_record as LINT  # noqa: E402
import emu_drvparam as E  # noqa: E402
import emu_record_selector as S  # noqa: E402

B, SIZE = 0x108000, F.SIZE
BUILD = "fx30_601"
X = locate_file.locate(BUILD, "cpapp-b.bin").read_bytes()
A = locate_file.locate("a7iv_602", "cpapp-b.bin").read_bytes()
SHA = hashlib.sha256(X).hexdigest()
IDS = 0xD10D68
NMODES = 31
MODES = (0x820, 0x880, 0x890, 0x8C0, 0x8D0)
COLMAP = 0x1039938
MATRIX, MROWS, MROW = 0x1038E48, 139, 20
GEO = 0xCB57A8                                     # 12-byte rows: u32 mode id, u16 x3, u16 window row
CROP, S0, S1, LC, RO = (0xD10DE4, 20), (0xE0278A, 38), (0xE02C24, 38), (0xE030BE, 14), (0xE03270, 14)
PAIR = {"L": 0xC79440, "R": 0xC79FF8}
DCI = {"L": 0xC76560, "R": 0xC77118}
P830 = {"L": 0xC7ABB0, "R": 0xC7B768}
# (stage rows, phase-detect rows p, read-out f2, window row) of each stock pair, and of the design
GEOM = {"8c0": (3356, 68, 41, 406), "dci": (3148, 64, 39, 510), "830": (3164, 64, 40, 502)}
NEW_ROW, NEW_H = 96, 3968
NEW = (NEW_H + 8, 82, 48, NEW_ROW)
OUT = (4336, 2438)
PAV = (27, 32)

u16 = lambda b, o: struct.unpack_from("<H", b, o)[0]
rd = lambda a, n: X[a - B:a - B + n]


def pair(at):
    return {h: rd(a, SIZE) for h, a in at.items()}


def pdaf_blocks(row, h, top=6, bottom=6):
    """Phase-detect blocks (rows 25 + 48 j) a window carries, by the margins the four stock movie windows allow (outer window: rows - 6 ..
    rows + h + 6; a block needs 31 rows after its start and 51 before its end at most, and is left out at 9 / 39 or less)."""
    lo, hi = row - top, row + h + bottom
    inside = [j for j in range(0, 100) if 25 + 48 * j - lo >= 31 and hi - (25 + 48 * j) > 51]
    unclear = [j for j in range(0, 100) if (9 < 25 + 48 * j - lo < 31) or (39 < hi - (25 + 48 * j) <= 51)]
    return inside, unclear


def check_sensor_facts():
    ids = list(struct.unpack_from("<%dI" % NMODES, X, IDS - B))
    idx = [ids.index(m) for m in MODES]
    assert idx == [2, 4, 5, 6, 7], idx
    col = struct.unpack_from("<%dI" % NMODES, X, COLMAP - B)
    assert all(col[i] == 1 for i in idx), "the five modes do not all use matrix column 1"
    rows = [rd(MATRIX + MROW * r, MROW) for r in range(MROWS)]
    assert rd(MATRIX + MROW * MROWS, MROW) == bytes(MROW), "matrix end row"
    for c in (2, 8, 9):
        assert all(r[4 + 1] == r[4 + c] for r in rows), f"matrix column {c} differs from column 1"
    for tbl in (CROP, S0, S1, LC, RO):
        base, n = tbl
        ref = rd(base + n * 6, n)
        assert all(rd(base + n * i, n) == ref for i in idx), f"table {base:#x}: the five modes' rows differ"
    geo = {}
    for r in range(40):
        mid = struct.unpack_from("<I", X, GEO - B + 12 * r)[0]
        if mid in MODES:
            geo[mid] = GEO + 12 * r
    assert sorted(geo) == sorted(MODES) and all(u16(X, a - B + 10) == 406 for a in geo.values())
    # stock rules on the stock movie modes (indices: 0x830 3, 0x28c0 14, 0x5c0 16, 0x8c0 6)
    for i in (3, 6, 14, 16):
        crop, lc, s0, s1, ro = (struct.unpack_from("<%dH" % (t[1] // 2), X, t[0] - B + t[1] * i) for t in (CROP, LC, S0, S1, RO))
        assert lc[6] == 25 + 48 * crop[9] and crop[3] == lc[4], (i, lc, crop)
        inside, unclear = pdaf_blocks(crop[3], s0[13], s0[11] + s0[12], s0[14] + s0[15])
        assert not unclear and inside[0] == crop[9] and len(inside) == s1[13], (i, inside, unclear, crop[9], s1[13])
        if i != 3:                                                       # 0x830 runs line 360: 2 f2 = p + 16 there
            assert 2 * ro[2] == s1[13] + 14 and ro[6] == (s0[13] + sum(s0[11:13]) + sum(s0[14:16])) // 2 + 24, (i, ro, s1[13])
    sel, _ = S.records(BUILD)
    assert all(sel[m] == [PAIR["L"], PAIR["R"]] for m in MODES), {hex(m): sel[m] for m in MODES}
    others = [hex(m) for m, r in sel.items() if m not in MODES and set(r) & set(PAIR.values())]
    assert not others, others
    return idx, geo


def cells(idx, geo):
    """(address, old bytes, new bytes) per table site: one site per table over the rows of indices 2..7 (row 3, 0x830, unchanged)."""
    inside, unclear = pdaf_blocks(NEW_ROW, NEW_H)
    assert not unclear and inside == list(range(2, 84)), (inside, unclear)
    p, k = len(inside), inside[0]
    f2 = (p + 14) // 2
    assert (p, f2) == (NEW[1], NEW[2]) and (p + 14) % 2 == 0
    ro6 = (NEW_H + 12) // 2 + 24
    sites, imgcells = [], []
    edits = {CROP: {3: NEW_ROW, 9: k}, S0: {13: NEW_H}, S1: {13: p}, LC: {4: NEW_ROW, 6: 25 + 48 * k}, RO: {2: f2, 6: ro6}}
    names = {CROP: "crop", S0: "stream-0 window", S1: "stream-1 (phase detect)", LC: "LC", RO: "read-out"}
    for tbl, ed in edits.items():
        base, n = tbl
        lo, hi = base + n * 2, base + n * 8
        old = bytearray(rd(lo, hi - lo))
        new = bytearray(old)
        for i in idx:
            for f, v in ed.items():
                struct.pack_into("<H", new, n * (i - 2) + 2 * f, v)
                imgcells.append((base + n * i + 2 * f, v))
        sites.append({"kind": "S", "addr": hex(lo), "old": bytes(old).hex(), "new": bytes(new).hex(), "where": "file",
                      "note": f"{names[tbl]} table {base:#x}, rows of indices 2-7 (0x820, 0x830 unchanged, 0x880, 0x890, 0x8c0, 0x8d0): "
                              + ", ".join(f"field {f} {u16(old, n * 4 + 2 * f)} -> {v}" for f, v in ed.items())})
    glo = min(geo.values())
    ghi = max(geo.values()) + 12
    old = bytearray(rd(glo, ghi - glo))
    new = bytearray(old)
    for m, a in geo.items():
        struct.pack_into("<H", new, a - glo + 10, NEW_ROW)
        imgcells.append((a + 10, NEW_ROW))
    sites.append({"kind": "S", "addr": hex(glo), "old": bytes(old).hex(), "new": bytes(new).hex(), "where": "file",
                  "note": f"geometry table (12-byte rows by mode id, A7 IV 0xc3dc40's form): window row 406 -> {NEW_ROW} in the rows of "
                          + ", ".join(hex(m) for m in sorted(geo)) + " (0x830's row inside the span unchanged)"})
    return sites, imgcells, {"p": p, "first_block": k, "f2": f2, "readout_length": ro6}


# ---------------------------------------------------------------- the row model

PACK = None


def fit_rules(M):
    """For every 16-bit field that differs between the stock 3356-row pair and the DCI pair: which rule the three stock pairs agree on."""
    recs = {n: pair(a) for n, a in (("8c0", PAIR), ("dci", DCI), ("830", P830))}
    cands = [("H", Fr(1)), ("H", Fr(1, 2)), ("H", Fr(1, 4)), ("p", Fr(1)), ("2f2", Fr(1)), ("H+2f2", Fr(1)), ("row", Fr(1))]

    def delta(kind, a, b):
        (ha, pa, fa, ra), (hb, pb, fb, rb) = GEOM[a], GEOM[b]
        return {"H": hb - ha, "p": pb - pa, "2f2": 2 * (fb - fa), "H+2f2": hb - ha + 2 * (fb - fa), "row": rb - ra}[kind]

    rules, column_like = {}, {}
    for h in "LR":
        rules[h], column_like[h] = {}, []
        for o in range(0, SIZE, 2):
            v = {n: u16(recs[n][h], o) for n in recs}
            if v["8c0"] == v["dci"] or o in M.packer:
                continue
            ok = []
            for kind, k in cands:
                if kind == "row":
                    if v["dci"] == GEOM["dci"][3] and v["8c0"] == GEOM["8c0"][3] and v["830"] == GEOM["830"][3]:
                        ok.append(("row", k))
                    continue
                if all(v["8c0"] + k * delta(kind, "8c0", n) == v[n] for n in ("dci", "830")):
                    ok.append((kind, k))
            if ok:
                rules[h][o] = ok[0]
            else:
                column_like[h].append(o)
    return rules, column_like


def apply_rules(rules, base, frm, to):
    out = {}
    for h in "LR":
        r = bytearray(base[h])
        for o, (kind, k) in rules[h].items():
            if kind == "row":
                v = to[3]
            else:
                d = {"H": to[0] - frm[0], "p": to[1] - frm[1], "2f2": 2 * (to[2] - frm[2]), "H+2f2": to[0] - frm[0] + 2 * (to[2] - frm[2])}[kind]
                v = u16(base[h], o) + k * d
                assert v.denominator == 1 and 0 <= v < 0x10000, (h, hex(o), v)
            struct.pack_into("<H", r, o, int(v))
        out[h] = bytes(r)
    return out


def build_pair(M, rules, base, frm, to, target):
    mod = apply_rules(rules, base, frm, to)
    rows = to[0]
    frame = (5976, rows)
    crop = (12, 4, 5952, rows - 8)
    got, facts = N.assemble(M, mod, target, frame=frame, crop=crop, mirror_as=base)
    return got, facts


def main():
    idx, geo = check_sensor_facts()
    sites, imgcells, sfacts = cells(idx, geo)
    M = F.Model(A)
    rules, column_like = fit_rules(M)
    # self-test: rebuild each real pair from the other
    p8, pd = pair(PAIR), pair(DCI)
    selftest = {}
    for name, base, frm, want, wname, target in (("dci_from_3356_pair", p8, GEOM["8c0"], pd, "dci", (4624, 2438)),
                                                  ("3356_pair_from_dci", pd, GEOM["dci"], p8, "8c0", (4336, 2438))):
        got, _ = build_pair(M, rules, base, frm, GEOM[wname], target)
        diff = {h: [hex(o) for o in range(0, SIZE, 2) if got[h][o:o + 2] != want[h][o:o + 2]] for h in "LR"}
        selftest[name] = diff
        print(f"self-test {name}: fields that differ L {len(diff['L'])} R {len(diff['R'])}", {h: d[:10] for h, d in diff.items() if d})
    # +0x5ac (a Cas word) follows the OUTPUT shape, not the rows: 4096 in every stock pair with a 16:9 output of the eight builds' 0x8c0-family
    # records (4110 for the FX30's 4624-wide DCI output, 4111-4114 on the Burano's DCI outputs); the A7 IV's squeezed full-height records keep 4096
    # and run on the camera (ogsq_v3, F682). The design's output is the stock 4336 x 2438, so the field stays stock; nothing else may differ.
    exact = all(d == {"L": ["0x5ac"], "R": ["0x5ac"]} for d in selftest.values())
    assert exact, "the row model does not rebuild the stock pairs"
    assert u16(p8["L"], 0x5AC) == u16(p8["R"], 0x5AC) == 4096
    # the design pair
    rec, facts = build_pair(M, rules, p8, GEOM["8c0"], NEW, OUT)
    lint, lf = LINT.lint_design_records(rec["L"], rec["R"])
    broken = {r: d for r, (ok, d) in lint.items() if not ok}
    assert not broken, broken
    lrc = {}
    for h in "LR":
        k = LINT.lrc(rec[h])
        lrc[h] = {"input": list(k["in"]), "output": list(k["out"]), "step_q12": list(k["step"]), "start": list(k["start"])}
        assert k["in"][1] == NEW[0] and u16(rec[h], 0x95E) == NEW_ROW
        assert rec[h][0x174:0x1D8] == p8[h][0x174:0x1D8], "something after the first stage moved"
    nfields = {h: sum(rec[h][x:x + 2] != p8[h][x:x + 2] for x in range(0, SIZE, 2)) for h in "LR"}
    for h, a in PAIR.items():
        sites.append({"kind": "R", "addr": hex(a), "old": p8[h].hex(), "new": bytes(rec[h]).hex(), "where": "file",
                      "note": f"{'left' if h == 'L' else 'right'} picture record of modes 0x820/0x880/0x890/0x8c0/0x8d0: first stage {NEW[0]} rows "
                              f"(crop 5952 x {NEW_H}), squeezed by Lrc into the stock {OUT[0]} x {OUT[1]} front end; {nfields[h]} fields differ"})
    sites.sort(key=lambda s: int(s["addr"], 16))
    # stored records: the FX30's own calculator, stock and with the cells, NTSC (60 Hz) and PAL (50 Hz) timing
    f = E.CONSTS[BUILD]["fields"]
    pal = [(f[0x2C], rd(f[0x30], 24 * NMODES))]
    stored = {}
    for system, base in (("ntsc", []), ("pal", pal)):
        st, l1 = E.records(BUILD, base)
        de, l2 = E.records(BUILD, base + imgcells)
        assert not l1 and not l2 and all(st[m][2] is None and de[m][2] is None for m in st)
        changed_modes = sorted(m for m in st if st[m][1] != de[m][1])
        assert changed_modes == sorted(MODES), [hex(m) for m in changed_modes]
        stored[system] = {m: (bytearray(st[m][1]), bytearray(de[m][1])) for m in MODES}
    # Each mode's record as the camera computes it at start-up: from the 60 Hz timing table (NTSC) or the 50 Hz one (PAL). The time values the
    # calculator derives from the line length (+0xbc, +0xea..+0xf0) differ a little between the two, so each record carries both variants over
    # one list of offsets (the union); the write level uses the variant whose stock (or new) bytes it finds, the same for all five records.
    ids_all = list(struct.unpack_from("<%dI" % NMODES, X, IDS - B))
    recs_out = {}
    for m in MODES:
        var = {}
        for system in ("ntsc", "pal"):
            s, d = stored[system][m]
            assert s[4:8] == b"\x01\x01\x01\x01"
            d[6], d[7] = PAV
            ex = {"height": u16(d, 0x66), "pdaf_rows": u16(d, 0x8C), "row": (u16(d, 0xF6), u16(d, 0x102)), "first_block": u16(d, 0x10E),
                  "readout_length": u16(d, 0x142), "first_pdaf_row": u16(d, 0x15A)}
            assert ex == {"height": NEW_H, "pdaf_rows": sfacts["p"], "row": (NEW_ROW, NEW_ROW), "first_block": sfacts["first_block"],
                          "readout_length": sfacts["readout_length"], "first_pdaf_row": 121}, ex
            var[system] = (bytes(s), bytes(d))
        offs = sorted({k for s, d in var.values() for k in range(len(s)) if s[k] != d[k]})
        pick = lambda b: bytes(b[k] for k in offs)
        sets = [pick(var["ntsc"][0]), pick(var["ntsc"][1]), pick(var["pal"][0]), pick(var["pal"][1])]
        assert len(set(sets)) == 4, f"{m:#x}: the NTSC/PAL stock/new byte sets are not all different at the sites"
        timing_only = [hex(k) for k in range(0, 0x160, 2) if k not in offs and var["ntsc"][0][k:k + 2] != var["pal"][0][k:k + 2]]
        recs_out[hex(m)] = {"index": ids_all.index(m), "offsets_that_differ": [hex(k) for k in offs],
                            "ntsc_pal_stock_differ_elsewhere_untouched": timing_only,
                            **{sy: {"stock": var[sy][0].hex(), "design": var[sy][1].hex(),
                                    "words": {hex(k): [u16(var[sy][0], k), u16(var[sy][1], k)] for k in range(0, 0x160, 2)
                                              if var[sy][0][k:k + 2] != var[sy][1][k:k + 2]}} for sy in var}}
        print(f"stored record {m:#06x}: {len(offs)} bytes are sites {[hex(k) for k in offs]}; NTSC and PAL variants differ at "
              f"{[hex(k) for k in offs if var['ntsc'][0][k] != var['pal'][0][k] or var['ntsc'][1][k] != var['pal'][1][k]]}")
    ev = ROOT / "evidence/fx30/sensor"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "ogsq_fx30_v1_stored_records_emu.json").write_text(json.dumps({
        "about": "Stored drive-parameter records (0x160 bytes) of the five modes that share the picture-record pair, from the FX30's own calculator "
                 "0x354204 (build/emu_drvparam.py fx30_601), stock and with ogsq_fx30_v1's table cells, plus the vertical sampling ratio 27/32 at +6/+7, "
                 "with the 60 Hz (ntsc) and the 50 Hz (pal) timing table. The sites are the union of the bytes either variant changes.",
        "records_base_in_emulation": hex(f[0x10]), "record_bytes": 0x160, "modes": recs_out}, indent=1) + "\n", encoding="utf8", newline="\n")
    (ev / "ogsq_fx30_v1_selftest.json").write_text(json.dumps({
        "about": "build/build_og_fx30.py self-test: the row model (fitted on the stock pairs 0xc79440 3356 rows, 0xc76560 3148 rows, 0xc7abb0 3164 rows) "
                 "with build_fhnative.assemble (planner columns, movie row rule, firmware packers) rebuilds each real pair from the other",
        "rules": {h: {hex(o): f"{k[0]}*{k[1]}" for o, k in sorted(rules[h].items())} for h in "LR"},
        "fields_left_stock_column_or_output_dependent": {h: [hex(o) for o in v] for h, v in column_like.items()},
        "rebuilds": selftest, "exact": exact}, indent=1) + "\n", encoding="utf8", newline="\n")
    out = {"design": "ogsq_fx30_v1", "build": BUILD,
           "title": "FX30 open gate, sensor side: 5952 x 3968 (3:2) window from row 96 in modes 0x820/0x880/0x890/0x8c0/0x8d0, first stage 5976 x 3976 "
                    "squeezed into the stock 4336 x 2438 front end, vertical sampling ratio 27/32",
           "artifact": "cpapp-b.bin", "artifact_sha256": SHA, "generated_by": "build/build_og_fx30.py",
           "ported_from": {"design": "ogsq_v3", "build": "a7iv_602", "how": "the A7 IV's mechanism (full-height window, Lrc squeeze, 27/32) rebuilt on the FX30's own tables and records"},
           "modes": [hex(m) for m in MODES], "mode_indices": idx,
           "summary": {"window": [5952, NEW_H], "window_row": NEW_ROW, "stock_window": [5952, 3348], "stock_window_row": 406,
                       "first_stage": [5976, NEW[0]], "front_end": list(OUT), "pdaf": sfacts, "line_periods_per_frame_24p": 4410,
                       "readout_line_periods": sfacts["readout_length"], "lrc": lrc, "record_fields_changed": nfields,
                       "sites": len(sites), "bytes": sum(len(s["old"]) // 2 for s in sites),
                       "expected_working_state": {"crop": [5952, NEW_H], "front_end": list(OUT), "second_scaler_takes": "the whole front end", "file": [3840, 2560]}},
           "patches": sites, "record_size": 0x160,
           "stored_records": {k: {"index": v["index"], "offsets_that_differ": v["offsets_that_differ"],
                                  "ntsc": {"stock": v["ntsc"]["stock"], "design": v["ntsc"]["design"]},
                                  "pal": {"stock": v["pal"]["stock"], "design": v["pal"]["design"]}} for k, v in recs_out.items()},
           "stored_record_note": "RAM, filled by the camera at start-up from the tables; records base = the drive-parameter object's +0x10 "
                                 "(emulation " + hex(f[0x10]) + ") + index x 0x160; the write level finds each mode's record through the pointer chain",
           "stored_record_extra": [{"offset": "0x6", "old": "01", "new": "%02x" % PAV[0], "note": "vertical sampling ratio, numerator"},
                                   {"offset": "0x7", "old": "01", "new": "%02x" % PAV[1], "note": "vertical sampling ratio, denominator"}],
           "evidence": ["evidence/fx30/sensor/ogsq_fx30_v1_selftest.json", "evidence/fx30/sensor/ogsq_fx30_v1_stored_records_emu.json"]}
    (ROOT / "modding/designs/ogsq_fx30_v1.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print(json.dumps(out["summary"]))


if __name__ == "__main__":
    main()
