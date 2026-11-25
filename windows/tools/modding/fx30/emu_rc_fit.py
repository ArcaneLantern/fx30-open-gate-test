"""Run the coprocessor's own resize calculation (cpapp-b.bin 6.02, RC calc 0xa2cabc -> core 0xa2c536 -> target calculation 0x13d518) alone
in Unicorn, on the input block the four-core emulation shows CalcRC (0x445a38) building for the stock full-frame 4K request, and compare
the result block with what the camera stored at 0x145091c (level 8 reads of requests 15 to 22).

Why: with a first stage taller than stock the second scaler takes only a centred part of the front-end picture (F680). The calculation
fits the mode's 16:9 aspect into the reference window (input block +0x34/+0x38 = 7008 x the stage's active rows) after multiplying heights
by a pixel aspect (working structure 0x11e1510 +0x48, Q12) that CalcRC builds from four bytes of the drive-parameter record (+4..+7:
horizontal numerator, denominator, vertical numerator, denominator; products at input block +4, +8, +0xc, +0x10).

The four-core emulation cannot show the cut: there the module's settings at 0x1452480.. are zero and the result is empty. Here the
settings this calculation reads are given values (SETTINGS below); they are assumptions, kept only because the firmware's own code then
returns the camera's numbers for the three camera cases. Nothing here is hardware.

  C:\\Python313\\python.exe -B build/emu_rc_fit.py [--trace]      writes evidence/pipeline/rc_fit_emu.json
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
BASE = 0x108000
IMG = next(p for p in (ROOT / "work/extracted/a7iv_602").rglob("cpapp-b.bin") if "nflasha8" in p.as_posix()).read_bytes()
MAP_LO, MAP_HI = 0x100000, 0x2600000
STACK_TOP, INP, PRM, OUTB, AUX, RET = 0x2200000, 0x2300000, 0x2300100, 0x2300200, 0x2300400, 0x2400000
STUB = {0xA32386, 0xA310E0, 0x56AB60}                         # log and trace calls
# The input block of the stock full-frame 4K request as CalcRC builds it (snapshot at 0xa2cabc, r0, in work/ogsq_v2/late24.json and
# the others: only +0x38 and the four products differ between designs). 20 words.
INPUT_4K = [2, 1, 1, 1, 1, 4336, 2438, 3840, 2160, 2176, 2438, 2160, 2438, 7008, 3942, 4240, 2832, 4240, 2832, 2]
# The parameter block's first 64 bytes at the same place (r1): mode 1 with 16:9 at +0x2c, +0x30, +0x32; the rest of the 0x9c bytes zero.
PARAM_4K = bytes.fromhex("00000000000000000000000000000000000000000000000001000000000000000000000000000000000000000100000010000900010000000000000000000000")
# Settings of the resize module that this calculation reads and that are zero in the four-core emulation. Assumed values:
#   0x14524a0, 0x14524a2  u16, multiplied into the horizontal and vertical unit (>> 8): 0x100 is one
#   0x1452498 bit 5       makes the result block's words +0x14, +0x18 the zoom value (16) as on the camera, not -1
SETTINGS = {0x14524A0: struct.pack("<H", 0x100), 0x14524A2: struct.pack("<H", 0x100), 0x1452498: b"\x20"}


def run(reference_rows, pa=(1, 1, 1, 1), settings=SETTINGS, trace=False, patch=None, input_words=None, param=None):
    """pa = record bytes +4..+7 (h num, h den, v num, v den). Returns the result block's ten u16 words and the working structure's fields."""
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    try:
        uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A15)
    except Exception:
        pass
    uc.mem_map(MAP_LO, MAP_HI - MAP_LO)
    uc.mem_write(BASE, IMG)
    uc.reg_write(A.UC_ARM_REG_C1_C0_2, uc.reg_read(A.UC_ARM_REG_C1_C0_2) | (0xF << 20))
    uc.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
    for a, b in settings.items():
        uc.mem_write(a, b)
    for a, b in (patch or {}).items():
        uc.mem_write(a, b)
    w = list(input_words or INPUT_4K)
    w[14] = reference_rows
    w[1], w[2], w[3], w[4] = pa[1], pa[3], pa[0], pa[2]         # +4 = (view 0xea) x h den, +8 = (0xec) x v den, +0xc = (0xe9) x h num, +0x10 = (0xeb) x v num; the view bytes are 1
    uc.mem_write(INP, struct.pack("<20I", *w))
    prm = param or PARAM_4K
    uc.mem_write(PRM, prm + bytes(0x9C - len(prm)))
    uc.mem_write(OUTB, b"\0" * 0x200)
    log = {"unmapped": [], "calls": []}

    def on_code(u, addr, size, _):
        if addr in STUB:
            u.reg_write(A.UC_ARM_REG_R0, 0)
            u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))
        elif addr == RET:
            u.emu_stop()
        elif trace and addr in (0xA2C2BE, 0xA2D65A, 0x9BB0CE, 0x9B3330, 0x9B3D78, 0x9B3D80, 0xA2D544, 0xA2C490, 0xA2C246, 0xA2DD8A):
            log["calls"].append((hex(addr), hex(u.reg_read(A.UC_ARM_REG_R0)), hex(u.reg_read(A.UC_ARM_REG_R1)), hex(u.reg_read(A.UC_ARM_REG_LR))))

    def on_unmapped(u, access, addr, size, value, _):
        log["unmapped"].append(hex(addr))
        return False

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    sp = STACK_TOP - 0x800
    for r, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), (INP, PRM, OUTB, AUX)):
        uc.reg_write(r, v)
    uc.reg_write(A.UC_ARM_REG_SP, sp)
    uc.reg_write(A.UC_ARM_REG_LR, RET | 1)
    err = None
    try:
        uc.emu_start(0xA2CABC | 1, RET, count=20_000_000)
    except UcError as e:
        err = f"{e} pc={uc.reg_read(A.UC_ARM_REG_PC):#x}"
    out = bytes(uc.mem_read(OUTB, 0x40))
    ws = bytes(uc.mem_read(0x11E1510, 0xDC))
    r = struct.unpack_from("<10H", out)
    return {"words": list(r), "more": list(struct.unpack_from("<5i", out, 0x14)),
            "start": [round(r[2] + r[6] / 4096, 4), round(r[3] + r[7] / 4096, 4)], "size": [round(r[4] + r[8] / 4096, 4), round(r[5] + r[9] / 4096, 4)],
            "pixel_aspect_q12": struct.unpack_from("<i", ws, 0x48)[0], "scale_h_q12": struct.unpack_from("<i", ws, 0x4C)[0],
            "scale_v_q12": struct.unpack_from("<i", ws, 0x50)[0], "zoom_q16": struct.unpack_from("<i", ws, 0x24)[0],
            "error": err, "unmapped": log["unmapped"][:6], "calls": log["calls"][:60]}


def main():
    trace = "--trace" in sys.argv
    cam = json.loads((ROOT / "evidence/camera/CT6_2026-11-18/request22_runs.json").read_text(encoding="utf8"))["second_scaler_block_0x145091c"]["every_level8_run"]
    seen = {}
    for t in cam:                                                # one camera block for each reference height of the 4K mode
        if t["readout"][0] == 7032:
            seen.setdefault(t["readout"][1] - 16, t)
    rows = []
    for ref, t in sorted(seen.items()):
        e = run(ref, trace=trace)
        rows.append({"reference_window": [7008, ref], "camera_session": t["session"], "camera_words": t["block_words"], "emulated_words": e["words"],
                     "equal": e["words"] == t["block_words"], "emulated": {k: e[k] for k in ("start", "size", "pixel_aspect_q12", "scale_h_q12", "scale_v_q12", "zoom_q16", "error", "unmapped")}})
        print("reference 7008 x %d: camera %s\n%sfirmware code %s  %s" % (ref, t["block_words"], " " * 19, e["words"], "EQUAL" if e["words"] == t["block_words"] else "differs"), e["error"] or "")
        if trace:
            for c in e["calls"]:
                print("   call", c)
    pred = []
    for name, ref, pa in (("ogsq_v2 (camera: a 16:9 cut)", 4672, (1, 1, 1, 1)), ("ogsq_v3: vertical ratio 27/32", 4672, (1, 1, 27, 32)),
                          ("for comparison: horizontal ratio 32/27", 4672, (32, 27, 1, 1)), ("stock 4K", 3942, (1, 1, 1, 1))):
        e = run(ref, pa)
        pred.append({"case": name, "reference_window": [7008, ref], "record_bytes_4_7": list(pa), **{k: e[k] for k in ("words", "start", "size", "pixel_aspect_q12", "error")}})
        print("%-42s pixel aspect %d: takes %s x %s from %s  %s" % (name, e["pixel_aspect_q12"], e["size"][0], e["size"][1], e["start"], e["error"] or ""))
    # The earlier 3840 by 2560 design (og4k_data_v1): the first scaler gives 3840 by 2560 directly. Input blocks from its four-core runs
    # (work/og4k/sub24.json: its 13 sites with the stock 4K request; og4k24.json: the whole design, a 3:2 request for 3840 by 2560).
    sub = [2, 1, 1, 1, 1, 3840, 2560, 3840, 2160, 1928, 2560, 1912, 2560, 7008, 4672, 4240, 2832, 4240, 2832, 2]
    og = [2, 1, 1, 1, 1, 3840, 2560, 3840, 2560, 1928, 2560, 1912, 2560, 7008, 4672, 4240, 2832, 4240, 2832, 2]
    p32 = bytes.fromhex("00000000000000000000000000000000000000000000000001000000000000000000000000000000000000000200000003000200010000000000000000000000")
    fe = []
    for name, words, pa, prm in (("og4k_data_v1 sites, stock 4K request (16:9), sampling 1/1", sub, (1, 1, 1, 1), None),
                                 ("the same with the vertical ratio 27/32", sub, (1, 1, 27, 32), None),
                                 ("whole og4k_data_v1: 3:2 request, 3840 by 2560 out", og, (1, 1, 1, 1), p32)):
        e = run(4672, pa, input_words=words, param=prm)
        fe.append({"case": name, "source": words[5:7], "reference_window": [7008, 4672], "record_bytes_4_7": list(pa),
                   **{k: e[k] for k in ("words", "start", "size", "pixel_aspect_q12", "scale_h_q12", "scale_v_q12", "error")}})
        print("%-58s takes %s x %s from %s  %s" % (name, e["size"][0], e["size"][1], e["start"], e["error"] or ""))
    out = {"about": "The firmware's own resize calculation (0xa2cabc -> 0xa2c536 -> 0x13d518) run alone on the input block of the stock full-frame 4K request, "
                    "with the reference rows and the record's four sampling bytes varied. Compared with the block the camera stored at 0x145091c. "
                    "build/emu_rc_fit.py. The module settings listed are assumptions (zero in the four-core emulation); hardware is not modelled.",
           "assumed_settings": {hex(a): b.hex() for a, b in SETTINGS.items()}, "input_block_words": INPUT_4K, "parameter_block_first_64_bytes": PARAM_4K.hex(),
           "against_the_camera": rows, "all_camera_cases_reproduced": all(r["equal"] for r in rows), "cases": pred, "front_end_3840x2560": fe}
    (ROOT / "evidence/pipeline/rc_fit_emu.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("all camera cases reproduced:", out["all_camera_cases_reproduced"])


if __name__ == "__main__":
    main()
