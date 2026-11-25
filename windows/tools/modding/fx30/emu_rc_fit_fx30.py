"""FX30 6.01 port (2026-11-26): build/emu_rc_fit.py's resize calculation run on the FX30's own code.

  C:\\Python313\\python.exe -B build\\emu_rc_fit_fx30.py      -> evidence/fx30/sensor/rc_fit_fx30_emu.json

The FX30's resize calculation is the A7 IV's: the entry 0xa8c274 equals the A7 IV's 0xa2cabc over 200 bytes (match_thumb), and the core
0xa8bcee lines up with 0xa2c536 call for call (diff_consts; one more local on the stack). Its working structure is 0x12ddef8 (A7 IV
0x11e1510), its module settings 0x1573a30.. (A7 IV 0x1452488..) and its target calculation 0x13d6f0 (A7 IV 0x13d518).

Run with the same assumed settings as the A7 IV run (which reproduce the A7 IV camera's result blocks in all three camera cases) and the
A7 IV's input block with the FX30's reference width (5952) and rows. The FX30's path makes one call the A7 IV's does not (0xa8f67e: a hardware
command through the message buffer 0x5077e4 / 0x507118 / 0x5078e0); the buffer get is handed a scratch buffer, the OS call 0x594af8 and the
log print 0x5c1178 are stubbed. No FX30 camera block exists to compare with; the A7 IV's code is run on the same cases for comparison.
Pass: with the vertical sampling ratio 27/32 the second scaler takes the whole front end; with 1/1 it takes a 16:9 cut (as ogsq_v2 did on the A7 IV).
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402
import emu_rc_fit as AIV  # noqa: E402

IMG = locate_file.locate("fx30_601", "cpapp-b.bin").read_bytes()
BASE = 0x108000
MAP_LO, MAP_HI = 0x100000, 0x2600000
STACK_TOP, INP, PRM, OUTB, AUX, RET, SCRATCH = 0x2200000, 0x2300000, 0x2300100, 0x2300200, 0x2300400, 0x2400000, 0x2500000
ENTRY, WORK = 0xA8C274, 0x12DDEF8
MSG_GET = 0x5077E4
STUB = {0x5C1178, 0x594AF8}
SHIFT = 0x1573A30 - 0x1452488
SETTINGS = {a + SHIFT: b for a, b in AIV.SETTINGS.items()}


def run(ref, pa=(1, 1, 1, 1), width=5952):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    try:
        uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A15)
    except Exception:
        pass
    uc.mem_map(MAP_LO, MAP_HI - MAP_LO)
    uc.mem_write(BASE, IMG)
    uc.reg_write(A.UC_ARM_REG_C1_C0_2, uc.reg_read(A.UC_ARM_REG_C1_C0_2) | (0xF << 20))
    uc.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
    for a, b in SETTINGS.items():
        uc.mem_write(a, b)
    w = list(AIV.INPUT_4K)
    w[13], w[14] = width, ref
    w[1], w[2], w[3], w[4] = pa[1], pa[3], pa[0], pa[2]
    uc.mem_write(INP, struct.pack("<20I", *w))
    uc.mem_write(PRM, AIV.PARAM_4K + bytes(0xBC - len(AIV.PARAM_4K)))
    uc.mem_write(OUTB, b"\0" * 0x200)
    log = {"unmapped": [], "stubbed": 0}

    def on_code(u, addr, size, _):
        if addr == MSG_GET:                              # message-buffer get: hand out a scratch buffer
            u.mem_write(u.reg_read(A.UC_ARM_REG_R1), struct.pack("<I", SCRATCH))
            log["stubbed"] += 1
            u.reg_write(A.UC_ARM_REG_R0, 0)
            u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))
        elif addr in STUB:
            log["stubbed"] += 1
            u.reg_write(A.UC_ARM_REG_R0, 0)
            u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))
        elif addr == RET:
            u.emu_stop()

    def on_unmapped(u, access, addr, size, value, _):
        log["unmapped"].append(hex(addr))
        return False

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    for r, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), (INP, PRM, OUTB, AUX)):
        uc.reg_write(r, v)
    uc.reg_write(A.UC_ARM_REG_SP, STACK_TOP - 0x800)
    uc.reg_write(A.UC_ARM_REG_LR, RET | 1)
    err = None
    try:
        uc.emu_start(ENTRY | 1, RET, count=20_000_000)
    except UcError as e:
        err = f"{e} pc={uc.reg_read(A.UC_ARM_REG_PC):#x}"
    out = bytes(uc.mem_read(OUTB, 0x40))
    ws = bytes(uc.mem_read(WORK, 0xDC))
    r = struct.unpack_from("<10H", out)
    return {"words": list(r), "start": [round(r[2] + r[6] / 4096, 4), round(r[3] + r[7] / 4096, 4)],
            "size": [round(r[4] + r[8] / 4096, 4), round(r[5] + r[9] / 4096, 4)],
            "pixel_aspect_q12": struct.unpack_from("<i", ws, 0x48)[0], "error": err, "unmapped": log["unmapped"][:4]}


def main():
    res = {"about": __doc__, "assumed_settings": {hex(a): b.hex() for a, b in SETTINGS.items()}, "cases": {}}
    for name, ref, pa in (("stock 16:9 window 5952x3348", 3348, (1, 1, 1, 1)),
                          ("open gate 5952x3968, ratio 1/1 (the A7 IV's ogsq_v2 case)", 3968, (1, 1, 1, 1)),
                          ("open gate 5952x3968, ratio 27/32 (ogsq_fx30_v1)", 3968, (1, 1, 27, 32))):
        e = run(ref, pa)
        a = AIV.run({3348: 3942, 3968: 4672}[ref], pa)
        res["cases"][name] = {"fx30": e, "a7iv_same_case_7008_wide": {k: a[k] for k in ("start", "size", "pixel_aspect_q12")}}
        print(f"{name:58} FX30 takes {e['size']} from {e['start']} (pixel aspect {e['pixel_aspect_q12']}) {e['error'] or ''}"
              f" | A7 IV {a['size']} from {a['start']}")
    c = res["cases"]
    ok = (all(v["fx30"]["error"] is None for v in c.values())
          and c["stock 16:9 window 5952x3348"]["fx30"]["size"][1] > 2437.9
          and c["open gate 5952x3968, ratio 1/1 (the A7 IV's ogsq_v2 case)"]["fx30"]["size"][1] < 2100
          and c["open gate 5952x3968, ratio 27/32 (ogsq_fx30_v1)"]["fx30"]["size"][1] > 2437.9
          and c["open gate 5952x3968, ratio 27/32 (ogsq_fx30_v1)"]["fx30"]["start"][1] < 1)
    res["lever_keeps_every_row"] = ok
    out = ROOT / "evidence/fx30/sensor/rc_fit_fx30_emu.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
    print("27/32 keeps every row:", ok)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
