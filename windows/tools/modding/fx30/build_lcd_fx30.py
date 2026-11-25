"""Design lcd32dsq_fx30_v1: the FX30 6.01 rear screen shows the open-gate live view at 3:2, and the FX30's own De-Squeeze Display
stays right for that picture. The FX3 kit's screen step (lcd32dsq_fx3_v1, build/build_lcd_fx3.py), ported to the FX30.

  work\\venv\\Scripts\\python.exe -I -B build\\build_lcd_fx30.py        writes modding/designs/lcd32dsq_fx30_v1.json

Why the FX3 design carries over (every fact asserted below against the FX30 6.01 and FX3 7.02 cpapp-b.bin):
  - The FX30's VDF layout code is the FX3's, not the A7 IV / FX2 form (although the FX30's sensor tables have the A7 IV's layout). The
    fit-mode function, the picture-ratio function, the de-squeeze calculator, the automatic layout and the panel-code function are the
    FX3's moved by +0x3890 as one block (0x1df458 -> 0x1e2ce8 ...), the 2.0x input crop and its callees by +0x68bd6 (0x5faf04 ->
    0x663ada), the three frame checks sit at the FX3's addresses (0x128438, 0x128d60, 0x1297e8): every instruction equal but for the
    relocated calls and table addresses. The frame tables (0xde78dc / 0xde7954 / 0xde79cc) are the FX3's byte for byte.
  - So every site word of lcd32dsq_fx3_v1 has its exact twin here, with the same stock and new bytes (asserted), at the mapped address.
The open-gate live view is a 16:9 frame (picture aspect code 2) that holds the whole 3:2 sensor area squeezed vertically (32/27), as
on the A7 IV and FX3. Three groups of words, all in the FX30's coprocessor image (cpapp-b.bin, loaded at 0x108000; changed in RAM only):

(a) The picture-ratio function 0x1e3024 (FX3 0x1df794): with fit mode 3 (letterbox) it gives a 16:9 picture the height width x 9/16.
    9/16 -> 2/3 (the function's own 3:2 case's constants):  0x1e3048  mov.w lr, #9 -> #2;  0x1e304c  movs r0, #16 -> #3.
    The FX30's rear monitor is 2,359,296 dots (Sony) = 1024 x 768 x 3: a 4:3 panel, as the FX3's 800 x 600 (whose type byte a camera read
    as 2 = 4:3). 1024 x 768 gets 684 rows from row 42; on a 3:2 panel (in case the type byte says 3) the height would exceed the panel,
    so the function gives the whole panel. The fit words of a 16:9 picture (0x1e2d38 / 0x1e2d3c: 3 on a 4:3 and on a 3:2 panel) stay.
(b) The frame widgets' rectangle tables (cpActAfWindow 0xde78dc, cpActAfWindowRemoteSend 0xde7954, cpActTrackingFrame 0xde79cc; the
    checks compare the live-view rectangle with an entry within 5 units of a 640 x 480 grid), 16:9 column:
      row 0 (rear output, 4:3 panel; stock (0, 60, 640, 360)) and row 2 (second output) -> (0, 26, 640, 428)
      row 1 (rear output, 3:2 panel; stock (0, 38, 640, 404))                           -> (0, 0, 640, 480)
    so the focus frames are drawn on either panel shape. The panel type is a byte the camera copies from its settings memory at start-up
    (rear: RAM 0x16295b8 + 0x1c = 0x16295d4, read by 0x647c42; FX3 0x14909e4): 2 = 4:3, 3 = 3:2, 1 = 16:9 (0x1e38e0, tables 0x1e3984 /
    0xc44f34, the FX3's).
(c) The de-squeeze calculator 0x1e2f10 (FX3 0x1df680), used instead of (a) while De-Squeeze Display is on (0x677744): full width,
    centred, height = (width x n + 2d) / d & ~3 with fixed per-factor ratios for a 16:9 picture. The FX30's menu (Ver. 6.00 and later)
    offers 1.3x, 1.5x, 1.6x (a 1.65 correction) and 2.0x: the calculator's codes 1..4 (the input command refuses a code >= 5, 0x65e028).
    For a picture that is 3:2:
      1.3x   0x1e2f90 / 0x1e2f94  45/104 -> 20/39   (shown 1.95:1)
      1.5x   0x1e2f98 / 0x1e2f9c   3/8   ->  4/9    (2.25:1)
      1.65x  0x1e2fa0 / 0x1e2fa4  15/44  -> 40/99   (2.475:1)
      2.0x   0x1e2f38 / 0x1e2f3c   3/8   ->  1/3    (3:1, the whole 3:2 frame: the owner's choice on the FX3, 2026-11-24)
    and the 2.0x centre crop is turned off: 0x663ada crops the input to a centre 4:3 when the code is 4, on both of its paths; the
    compares at 0x663b0c and 0x663b3e go from `cmp r0, #4` to `cmp r0, #5` (never: the code is always below 5).
    The 17:9 ratios, the HDMI manual-layout copy and the fit words stay stock.

While applied, every 16:9 picture is shown at 3:2 on the rear screen and the de-squeeze ratios are those of a 3:2 picture (other movie
formats look wrong there until the screen step is put back); HDMI's own layout is unchanged. Nothing here talks to a camera.
Checked by build/emu_lcd_fx30.py (Unicorn, the FX30's own functions) and build/lcd_fx30_qemu.py (qemu-arm, the leaf calculators).
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

NAME = "lcd32dsq_fx30_v1"
B = 0x108000
FX = locate_file.locate("fx30_601", "cpapp-b.bin").read_bytes()
F3 = locate_file.locate("fx3_702", "cpapp-b.bin").read_bytes()
SHA = "2877ba56332e9157bfea7610b2ac8561e6edfbea9c26ff8bafa0531f8fe3a247"
assert hashlib.sha256(FX).hexdigest() == SHA
MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
fx = lambda a, n: FX[a - B:a - B + n]
f3 = lambda a, n: F3[a - B:a - B + n]

# FX3 7.02 -> FX30 6.01: the VDF block (fit, de-squeeze, ratio, layout, panel code) moved by +0x3890, the crop block by +0x68bd6
VDF, CROP_SHIFT = 0x3890, 0x68BD6
FX3_DESIGN = json.loads((ROOT / "modding/designs/lcd32dsq_fx3_v1.json").read_text(encoding="utf8"))


def port(a3):
    """FX30 address of an FX3 7.02 address in the screen code or its tables"""
    if 0x1DF000 <= a3 < 0x1E0200:
        return a3 + VDF
    if 0x5F5000 <= a3 < 0x612000:
        return a3 + CROP_SHIFT
    if 0xD2E510 <= a3 < 0xD2E678:
        return a3 - 0xD2E510 + 0xDE78DC
    raise ValueError(hex(a3))


RATIO_FN, FIT_FN, DSQ_FN, CROP_FN, LAYOUT_FN, PANEL_FN, FRAME_CHECK = 0x1E3024, 0x1E2CE8, 0x1E2F10, 0x663ADA, 0x1E3114, 0x1E38E0, 0x128438
TABLES = (("cpActAfWindow (focus area frames)", 0xDE78DC, 0xD2E510, 0x12852A),
          ("cpActAfWindowRemoteSend (the same frames for a remote viewer)", 0xDE7954, 0xD2E588, 0x128CDE),
          ("cpActTrackingFrame (tracking and face frames)", 0xDE79CC, 0xD2E600, 0x1294A6))
TABLE_LEN = 0x78
RECT_169 = {0: (0, 60, 640, 360), 1: (0, 38, 640, 404), 2: (0, 60, 640, 360)}
RECT_NEW = {0: (0, 26, 640, 428), 1: (0, 0, 640, 480), 2: (0, 26, 640, 428)}
ROWS = {0: "rear output, 4:3 panel", 1: "rear output, 3:2 panel", 2: "second output"}
PANEL_TYPE_REAR, PANEL_TYPE_SECOND = 0x16295D4, 0x1629704          # RAM: [0x16295b8 + 0x1c], [0x16296e8 + 0x1c] (0x647c42 / 0x647c54)
# (FX30 address, stock instruction, new instruction, what)
CODE = [(0x1E3048, ("mov.w", "lr, #9"), ("mov.w", "lr, #2"), "picture-ratio function, 16:9 picture: numerator 9 -> 2"),
        (0x1E304C, ("movs", "r0, #0x10"), ("movs", "r0, #3"), "picture-ratio function, 16:9 picture: denominator 16 -> 3"),
        (0x1E2F90, ("mov.w", "sl, #0x2d"), ("mov.w", "sl, #0x14"), "de-squeeze 1.3x, 16:9 picture: 45 -> 20"),
        (0x1E2F94, ("movs", "r5, #0x68"), ("movs", "r5, #0x27"), "de-squeeze 1.3x: 104 -> 39 (height = width x 20/39: 1.95:1)"),
        (0x1E2F98, ("mov.w", "sl, #3"), ("mov.w", "sl, #4"), "de-squeeze 1.5x, 16:9 picture: 3 -> 4"),
        (0x1E2F9C, ("movs", "r5, #8"), ("movs", "r5, #9"), "de-squeeze 1.5x: 8 -> 9 (4/9: 2.25:1)"),
        (0x1E2FA0, ("mov.w", "sl, #0xf"), ("mov.w", "sl, #0x28"), "de-squeeze 1.6x (1.65), 16:9 picture: 15 -> 40"),
        (0x1E2FA4, ("movs", "r5, #0x2c"), ("movs", "r5, #0x63"), "de-squeeze 1.6x (1.65): 44 -> 99 (40/99: 2.475:1)"),
        (0x1E2F38, ("mov.w", "sl, #3"), ("mov.w", "sl, #1"), "de-squeeze 2.0x (the default ratio, used only by code 4): 3 -> 1"),
        (0x1E2F3C, ("movs", "r5, #8"), ("movs", "r5, #3"), "de-squeeze 2.0x: 8 -> 3 (1/3: 3:1, the whole 3:2 frame)"),
        (0x663B0C, ("cmp", "r0, #4"), ("cmp", "r0, #5"), "2.0x centre crop, first path: code 4 -> 5 (never): no crop"),
        (0x663B3E, ("cmp", "r0, #4"), ("cmp", "r0, #5"), "2.0x centre crop, second path: code 4 -> 5 (never): no crop")]
ENC = {("mov.w", "lr, #2"): "4ff0020e", ("movs", "r0, #3"): "0320", ("mov.w", "sl, #0x14"): "4ff0140a", ("movs", "r5, #0x27"): "2725",
       ("mov.w", "sl, #4"): "4ff0040a", ("movs", "r5, #9"): "0925", ("mov.w", "sl, #0x28"): "4ff0280a", ("movs", "r5, #0x63"): "6325",
       ("mov.w", "sl, #1"): "4ff0010a", ("movs", "r5, #3"): "0325", ("cmp", "r0, #5"): "0528"}
rect = lambda r: struct.pack("<4H", *r)


def insn(data, addr):
    i = next(MD.disasm(data, addr), None)
    return (i.mnemonic, i.op_str, i.size) if i else None


def listing(img, a, n):
    return [(i.address - a, i.mnemonic, i.op_str, bytes(i.bytes)) for i in MD.disasm(img[a - B:a - B + n], a)]


def same_code(a3, a30, n, allowed=()):
    """the FX3's function at a3 and the FX30's at a30: the same instructions; only `allowed` offsets (calls, table addresses) may differ"""
    l3, l30 = listing(F3, a3, n), listing(FX, a30, n)
    assert len(l3) == len(l30) and len(l3) > 10, (hex(a30), len(l3), len(l30))
    differ = [o for (o, m, _, b), (o2, m2, _, b2) in zip(l3, l30) if b != b2 or o != o2 or m != m2]
    assert all(o in allowed for o in differ), (hex(a30), [hex(o) for o in differ])
    return len(l3), len(differ)


def movw_movt(img, addr):
    i = list(MD.disasm(img[addr - B:addr - B + 24], addr))
    assert i[0].mnemonic == "movw", (hex(addr), i[0].mnemonic)
    rd, lo = i[0].op_str.split(", #")
    hi = next(x for x in i[1:] if x.mnemonic == "movt" and x.op_str.startswith(rd + ","))
    return int(hi.op_str.split("#")[1], 16) << 16 | int(lo, 16)


def check_context():
    """Facts the design rests on, each read from the FX30 image (and the FX3 7.02 image where it is the reference)."""
    facts = {}
    # the leaf calculators and the fit function are the FX3's, byte for byte (position-independent code and their tables)
    for a3, n, what in ((0x1DF458, 0x94, "fit-mode function with its tables"), (0x1DF680, 0x114, "de-squeeze calculator"),
                        (0x1DF794, 0xF0, "picture-ratio function")):
        assert fx(port(a3), n) == f3(a3, n), what
    # the automatic layout: the FX3's, only its 16 calls relocated; it calls fit, de-squeeze active test, the calculator and the ratio function
    facts["layout_instructions"] = same_code(0x1DF884, LAYOUT_FN, 0x2A0, allowed={0x80, 0x8A, 0x98, 0xA6, 0xB4, 0xF0, 0x10C, 0x11E, 0x126, 0x12A,
                                                                                  0x19C, 0x1B0, 0x1C0, 0x1D8, 0x202, 0x25A})
    calls = [i.op_str for i in MD.disasm(fx(LAYOUT_FN, 0x2A0), LAYOUT_FN) if i.mnemonic == "bl"]
    for target in (0x677744,):
        assert "#%#x" % target in calls, hex(target)
    # the crop function and the de-squeeze code check: the FX3's, moved with their callees as one block
    assert fx(CROP_FN, 0xA0) == f3(0x5FAF04, 0xA0)
    assert fx(0x65E028, 6) == bytes.fromhex("0178052938bf") == f3(0x5F5452, 6)      # ldrb r1, [r0]; cmp r1, #5; it lo: codes 0..4 only
    # the frame checks: the FX3's at the same addresses, each forming its table's address; 640 x 480 grid, tolerance 5
    for what, t, t3, mv in TABLES:
        assert movw_movt(FX, mv) == t and movw_movt(F3, mv) == t3, what
        assert fx(t, TABLE_LEN) == f3(t3, TABLE_LEN), what
        for row, r in RECT_169.items():
            assert fx(t + 8 * (5 * row + 3), 8) == rect(r)
    facts["frame_check_instructions"] = same_code(0x128438, FRAME_CHECK, 0x200, allowed={0x18, 0x2A, 0x48, 0xB8, 0xC0, 0xE2, 0xE6, 0xF2, 0xFA, 0x1F4})
    assert struct.unpack("<d", fx(0x128600, 8))[0] == 640.0 and struct.unpack("<d", fx(0x1285F8, 8))[0] == 480.0
    assert fx(0x12854A, 4) == bytes.fromhex("b1ee041b")                      # vmov.f64 d1, #5.0
    # the ratio function's own 3:2 case, and the 16:9 case at the constants (the A7 IV's form; the A7S III's form is absent)
    assert insn(fx(0x1E3040, 4), 0x1E3040)[:2] == ("mov.w", "lr, #2") and insn(fx(0x1E3044, 2), 0x1E3044)[:2] == ("movs", "r0, #3")
    assert FX.count(bytes.fromhex("4ff0090e102007e0")) == 1 and FX.count(bytes.fromhex("4ff0090e08bf1020")) == 0
    # fit words: a 16:9 picture is letterboxed on a 4:3 (code 0) and a 3:2 (code 1) panel
    assert struct.unpack("<6I", fx(0x1E2D38, 24)) == (3, 3, 0, 0, 0, 2)
    # panel type: rear byte [0x16295b8 + 0x1c] (>= 4 -> 1), second output [0x16296e8 + 0x1c] (>= 2 -> 2); type -> code tables as the FX3
    assert movw_movt(FX, 0x647C42) == PANEL_TYPE_REAR - 0x1C and fx(0x647C4A, 4) == bytes.fromhex("007f0428")
    assert movw_movt(FX, 0x647C54) == PANEL_TYPE_SECOND - 0x1C
    facts["panel_code_instructions"] = same_code(0x1E0050, PANEL_FN, 0xC0, allowed={0x16, 0x32, 0x3C, 0x40})
    assert movw_movt(FX, 0x1E391C) == 0xC44F34 and fx(0xC44F34, 16) == f3(0xB7F034, 16) and fx(0x1E3984, 16) == f3(0x1E00F4, 16)
    # the display timing table is the FX3's / A7S III's (9 x 800x600, 3 x 720x480, 1024x768 entries): it does not tell the panel shape
    return facts


def design():
    facts = check_context()
    sites, words = [], {}
    for a, old, new, what in CODE:
        got = insn(fx(a, 4), a)
        assert got[:2] == old, (hex(a), got, old)
        enc = bytes.fromhex(ENC[new])
        assert len(enc) == got[2] and insn(enc + b"\x00\x00", a)[:2] == new, (hex(a), new)
        w = a & ~3
        cur = bytearray(words.get(w, fx(w, 4)))
        cur[a - w:a - w + len(enc)] = enc
        words[w] = bytes(cur)
        words.setdefault(("what", w), []).append(what)
    for w in sorted(k for k in words if isinstance(k, int)):
        sites.append({"ram_address": hex(w), "old": fx(w, 4).hex(), "new": words[w].hex(), "note": "; ".join(words[("what", w)])})
    for what, t, t3, _ in TABLES:
        for row in (0, 1, 2):
            e = t + 8 * (5 * row + 3)
            old, new = rect(RECT_169[row]), rect(RECT_NEW[row])
            for off, part in ((0, "x, y"), (4, "w, h")):
                if old[off:off + 4] != new[off:off + 4]:
                    sites.append({"ram_address": hex(e + off), "old": old[off:off + 4].hex(), "new": new[off:off + 4].hex(),
                                  "note": "%s, row %d (%s), 16:9 column, %s: %s to %s (FX3 %#x)" % (what, row, ROWS[row], part, RECT_169[row], RECT_NEW[row],
                                                                                              t3 + 8 * (5 * row + 3) + off)})
    # every changed instruction is the FX3 design's twin: the FX3 image with lcd32dsq_fx3_v1 applied holds the same new bytes at the ported
    # instruction (the crop block moved by 0x68bd6, not a multiple of 4, so its site words hold other neighbours than the FX3's words)
    f3_new = bytearray(F3)
    for s3 in FX3_DESIGN["sites"]:
        a3 = int(s3["ram_address"], 16)
        assert f3_new[a3 - B:a3 - B + 4] == bytes.fromhex(s3["old"])
        f3_new[a3 - B:a3 - B + 4] = bytes.fromhex(s3["new"])
    unport = lambda a30: a30 - VDF if 0x1E2000 <= a30 < 0x1E3A00 else a30 - CROP_SHIFT if 0x65E000 <= a30 < 0x67B000 else a30 - 0xDE78DC + 0xD2E510
    fx_new = bytearray(FX)
    for s_ in sites:
        a30 = int(s_["ram_address"], 16)
        fx_new[a30 - B:a30 - B + 4] = bytes.fromhex(s_["new"])
    changed30 = [k + B for k in range(len(FX)) if FX[k] != fx_new[k]]
    changed3 = [k + B for k in range(len(F3)) if F3[k] != f3_new[k]]
    assert sorted(unport(a) for a in changed30) == changed3, "the changed bytes are not the FX3 design's, ported"
    assert all(fx_new[a - B] == f3_new[unport(a) - B] for a in changed30)
    assert len(sites) == len(FX3_DESIGN["sites"]) == 30
    G = lambda a, n, note: {"ram_address": hex(a), "bytes": fx(a, n).hex(), "note": note + ", as in the file"}
    guards = [G(RATIO_FN, 16, "first 16 bytes of the picture-ratio function 0x1e3024"),
              G(0x1E3038, 16, "the ratio function's case table and its own 3:2 case (lr 2, r0 3)"),
              G(0x1E3050, 16, "the ratio function after the 16:9 case (1:1 and 17:9 cases)"),
              G(FIT_FN, 16, "first 16 bytes of the fit-mode function 0x1e2ce8"),
              G(0x1E2D38, 8, "fit mode of a 16:9 picture on a 4:3 and on a 3:2 panel: 3, 3 (letterbox: what makes the ratio count)"),
              G(DSQ_FN, 16, "first 16 bytes of the de-squeeze calculator 0x1e2f10"),
              G(0x1E2F20, 16, "the calculator's read of the de-squeeze code (accessor slot 0x758) and its range check"),
              G(0x1E2F40, 16, "the code table and the 1.3x 17:9 branch (17:9 ratios left alone)"),
              G(0x1E2F80, 16, "the whole-output path before the 16:9 ratios"),
              G(0x1E2FA8, 16, "the height calculation after the ratios"),
              G(0x663ADC, 16, "the input-crop function 0x663ada from its second halfword (de-squeeze active test)"),
              G(0x663AFC, 16, "the crop function's read of the de-squeeze code, up to the first code test"),
              G(0x663B10, 16, "the first crop path after the code test"),
              G(0x663B44, 16, "the second crop path after the code test (width = (4h + 6) / 3)")]
    for what, t, _, _ in TABLES:
        for row in (0, 1, 2):
            e = t + 8 * (5 * row + 3)
            guards += [G(e - 8, 8, "%s row %d, the entry before the 16:9 entry (1:1)" % (what.split(" ")[0], row)),
                       G(e + 8, 8, "%s row %d, the entry after the 16:9 entry (17:9)" % (what.split(" ")[0], row))]
    # each guard holds the FX3's bytes at the ported place (the crop guards are 4-aligned here, so they start 2 bytes off the FX3's)
    assert len(guards) == len(FX3_DESIGN["guards"])
    for g in guards:
        a30, n = int(g["ram_address"], 16), len(g["bytes"]) // 2
        assert f3(unport(a30), n).hex() == g["bytes"], g["ram_address"]
    spans = sorted([(int(s["ram_address"], 16), 4, "s") for s in sites] + [(int(g["ram_address"], 16), len(g["bytes"]) // 2, "g") for g in guards])
    assert all(a + n <= b for (a, n, _), (b, _, _) in zip(spans, spans[1:])), "a guard overlaps a site or a guard"
    assert all(int(s["ram_address"], 16) % 4 == 0 and fx(int(s["ram_address"], 16), 4) == bytes.fromhex(s["old"]) and s["old"] != s["new"] for s in sites)
    assert all(int(g["ram_address"], 16) % 4 == 0 and len(g["bytes"]) // 2 <= 16 for g in guards)
    return {"design": NAME, "build": "fx30_601", "camera": "ILME-FX30 (FX30), firmware 6.01",
            "title": "FX30 6.01: rear screen shows the open-gate live view at 3:2 (16:9 letterbox ratio 9/16 -> 2/3, frame widgets' 16:9 entries for both "
                     "panel shapes), and the built-in De-Squeeze Display ratios set for a 3:2 picture (1.3x 1.95:1, 1.5x 2.25:1, 1.6x (1.65) 2.475:1, "
                     "2.0x the whole frame at 3:1 with the centre 4:3 crop off)",
            "kind": "ram_words", "artifact": "cpapp-b.bin 6.01 (ILME-FX30), its loaded image in coprocessor RAM: the words are in the file, the change is made in RAM only",
            "artifact_sha256": SHA, "generated_by": "build/build_lcd_fx30.py",
            "ported_from": "lcd32dsq_fx3_v1 (FX3 7.02; its screen part works on two FX3s, 2026-11-24): the FX30's VDF code is the FX3's relocated, so the "
                           "30 words are the FX3 design's words at the ported addresses (asserted twin by twin), with the FX3's 32 guards ported (the four crop guards start 2 bytes later: the crop block moved by 0x68bd6)",
            "address_map_from_fx3_702": {"vdf_block": "+0x3890 (0x1df458.. -> 0x1e2ce8..)", "crop_block": "+0x68bd6 (0x5faf04 -> 0x663ada)",
                                         "frame_tables": "0xd2e510 / 0xd2e588 / 0xd2e600 -> 0xde78dc / 0xde7954 / 0xde79cc",
                                         "frame_checks": "same addresses (0x128438, 0x128d60, 0x1297e8)"},
            "checked_against_fx3": facts,
            "summary": {"sites": len(sites), "bytes": 4 * len(sites), "guards": len(guards),
                        "panel": "rear LCD 2,359,296 dots (Sony) = 1024 x 768: 4:3, panel code 0 from type byte 2 expected (type byte RAM 0x16295d4); "
                                 "the design also gives the right picture if the byte says 3 (3:2)",
                        "picture": "16:9 live view (aspect code 2) holding the whole 3:2 sensor area",
                        "ratio_stock": "9/16", "ratio_new": "2/3", "frame_rectangles_new": {ROWS[r]: list(v) for r, v in RECT_NEW.items()},
                        "desqueeze": {"1.3x (code 1)": "45/104 -> 20/39", "1.5x (code 2)": "3/8 -> 4/9", "1.6x = 1.65 (code 3)": "15/44 -> 40/99",
                                      "2.0x (code 4)": "3/8 -> 1/3, centre crop off"},
                        "goes_with": ["the FX30 open-gate state (sensor, output-size and encoder steps of fx30_601)"]},
            "while_applied": "every 16:9 picture on the rear screen is shown at 3:2 and the de-squeeze ratios are those of a 3:2 picture (other movie formats look "
                             "wrong there). 2.0x's ratio is the calculator's default for every picture shape and its crop is off for every shape, so 2.0x shows any "
                             "picture at 3:1 (the open-gate live view is always 16:9). HDMI's own layout and the 17:9 ratios of 1.3x / 1.5x / 1.6x are unchanged",
            "not_checked": ["on a camera: nothing of this design has run on an FX30",
                            "the FX30's rear panel type byte 0x16295d4 (expected 2 = 4:3 from Sony's 2,359,296 dots = 1024 x 768; a dump should read it)",
                            "that the FX30's menu sends codes 1 to 4 for 1.3x, 1.5x, 1.6x and 2.0x (inferred from the calculator's ratios, as on the FX3)",
                            "whether the focus frames are drawn while de-squeeze is on (the frame check has no de-squeeze input; stock behaves the same)"],
            "sites": sites, "guards": guards}


if __name__ == "__main__":
    d = design()
    out = ROOT / "modding" / "designs" / f"{NAME}.json"
    out.write_text(json.dumps(d, indent=1) + "\n", encoding="utf8", newline="\n")
    print("%s: %d sites, %d guards; sha %s" % (out.name, len(d["sites"]), len(d["guards"]), SHA[:16]))
    print("checked against the FX3:", d["checked_against_fx3"])
    for s in d["sites"]:
        print("  %s %s -> %s  %s" % (s["ram_address"], s["old"], s["new"], s["note"][:90]))
