"""FX30 6.01: what the SENSOR is programmed with per drive mode, from the firmware's own routine (FX30 port v2, 2026-11-26).

  C:\\Python313\\python.exe -B build\\emu_sensor_regs_fx30.py

The routine 0x8e8218 (r1 = drive-mode index) is the only code that names the register matrix: it takes the mode's column from the column map
0x1039938 and walks the matrix from 0x1038d1c, 20 bytes a row, until a null pointer, storing each row's column byte at the row's pointer (the
value byte of a 4-byte {register, value} entry of the register shadow, 0x1123de4 on). This runs it under Unicorn for every mode, on the stock
image and with design ogsq_fx30_v2's matrix site, and checks:
  - the walk covers 154 rows and starts at 0x1038d1c (v1 assumed 0x1038e48 / 139 rows and never saw registers 6/7, 8/9, 14, 16, 25);
  - stock, mode 0x8c0: the seven window registers are what a real camera held AFTER design v1 was applied
    (evidence/fx30/camera/2026-11-25_pal/02_after_patch_movie, a tester's dump): v1 left the sensor on the stock 3348-row window;
  - with v2: the five modes of column 1 get the new window (3968 rows from row 94) and nothing else changes, in any mode.
Writes evidence/fx30/sensor/sensor_regs_fx30_emu.json. Nothing is written to a firmware file or sent to a camera.
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import emu_drvparam as E  # noqa: E402

BUILD, BASE = "fx30_601", 0x108000
APPLY = 0x8E8218                                    # (this, mode index): matrix column -> register shadow
MATRIX, MROW, COLMAP, SHADOW0 = 0x1038D1C, 20, 0x1039938, 0x1123DE4
IDS, NMODES = 0xD10D68, 31
WINDOW_REGS = (6, 7, 8, 9, 14, 16, 25)
ROW_BIAS, MARGINS = 81, 12
MODES = (0x820, 0x880, 0x890, 0x8C0, 0x8D0)
STACK, RET = 0x2200000, 0x2400000
CAMERA = ROOT / "evidence/fx30/camera/2026-11-25_pal"


def run(image):
    """{mode id: ({register: value}, rows written)} with the routine run once per mode on a fresh copy of the image."""
    ids = struct.unpack_from("<%dI" % NMODES, image, IDS - BASE)
    out = {}
    for idx, mid in enumerate(ids):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0x100000, 0x2600000 - 0x100000)
        uc.mem_write(BASE, bytes(image))
        writes = []
        uc.hook_add(UC_HOOK_CODE, lambda u, a, s, _: u.emu_stop() if a == RET else None)
        uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, a, s, v, _: writes.append((a, s, v & 0xFF)))
        uc.reg_write(A.UC_ARM_REG_SP, STACK)
        uc.reg_write(A.UC_ARM_REG_LR, RET | 1)
        uc.reg_write(A.UC_ARM_REG_R0, 0x2300000)
        uc.reg_write(A.UC_ARM_REG_R1, idx)
        uc.emu_start(APPLY | 1, RET, count=100000)
        regs = {}
        for a, size, v in writes:
            slot, rem = divmod(a - SHADOW0, 4)
            q = struct.unpack_from("<H", image, a - 2 - BASE)[0]         # the register number the shadow entry carries
            assert size == 1 and rem == 2 and q not in regs and (q == slot or q > 0x31), (hex(a), size)
            regs[q] = (v, a)
        out[mid] = ({q: v for q, (v, _) in regs.items()}, len(writes), {q: a for q, (_, a) in regs.items()})
    return out


def window(regs):
    start, pairs = regs[6] | regs[7] << 8, regs[8] | regs[9] << 8
    return {"start_register": start, "line_pairs": pairs, "window_row": start - ROW_BIAS, "rows": 2 * pairs - MARGINS,
            "first_phase_detect_block": regs[14], "phase_detect_rows": 2 * regs[16], "readout_f2": regs[25]}


def camera_shadow(folder, where):
    pages = b"".join((CAMERA / folder / f"cp_shadow_{a:08x}.bin").read_bytes() for a in (0x1123000, 0x1124000))
    return lambda reg: pages[where[reg] - 0x1123000]


def main():
    stock_img = bytearray(E.image(BUILD))
    d = json.loads((ROOT / "modding/designs/ogsq_fx30_v2.json").read_text(encoding="utf8"))
    site = next(p for p in d["patches"] if "register matrix" in p["note"])
    a, old, new = int(site["addr"], 16), bytes.fromhex(site["old"]), bytes.fromhex(site["new"])
    assert stock_img[a - BASE:a - BASE + len(old)] == old
    v2_img = bytearray(stock_img)
    v2_img[a - BASE:a - BASE + len(new)] = new
    stock, v2 = run(stock_img), run(v2_img)
    rows = {n for _, n, _ in stock.values()}
    assert rows == {154}, rows
    s8, n8 = stock[0x8C0][0], v2[0x8C0][0]
    assert window(s8) == {"start_register": 487, "line_pairs": 1680, "window_row": 406, "rows": 3348, "first_phase_detect_block": 9,
                          "phase_detect_rows": 68, "readout_f2": 41}, window(s8)
    want = d["summary"]["sensor"]["registers"]
    for m in stock:
        changed = {r for r in stock[m][0] if stock[m][0][r] != v2[m][0][r]}
        assert changed == (set(WINDOW_REGS) if m in MODES else set()), (hex(m), sorted(changed))
        if m in MODES:
            assert all(stock[m][0][r] == want[str(r)][0] and v2[m][0][r] == want[str(r)][1] for r in WINDOW_REGS)
            assert stock[m][0] == s8 and v2[m][0] == n8, "the five modes of column 1 differ"
    w = window(n8)
    assert (w["window_row"], w["rows"]) == (d["summary"]["window_row"], d["summary"]["window"][1])
    assert (w["first_phase_detect_block"], w["phase_detect_rows"], w["readout_f2"]) == tuple(d["summary"]["pdaf"][k] for k in ("first_block", "p", "f2"))
    res = {"about": "build/emu_sensor_regs_fx30.py: the FX30's matrix-to-shadow routine 0x8e8218 run per drive mode, stock and with ogsq_fx30_v2",
           "routine": hex(APPLY), "matrix": hex(MATRIX), "rows_walked": 154, "column_map": hex(COLMAP), "shadow_base": hex(SHADOW0),
           "stock_0x8c0": window(s8), "v2_0x8c0": w,
           "modes_changed_by_v2": [hex(m) for m in stock if stock[m][0] != v2[m][0]],
           "registers_changed_by_v2": {str(r): [s8[r], n8[r]] for r in WINDOW_REGS},
           "stock_windows": {hex(m): window(r) for m, (r, _, _) in stock.items() if r.get(1) == 15}}
    print(f"routine {APPLY:#x}: 154 matrix rows per mode from {MATRIX:#x}")
    print("stock 0x8c0:", window(s8))
    print("v2    0x8c0:", w)
    # a real camera after design v1 (which did not touch the matrix), in movie mode: the window registers must be the stock ones
    if CAMERA.is_dir():
        cam = {}
        for folder in ("01_before_patch_stills", "02_after_patch_movie", "03_after_recording"):
            get = camera_shadow(folder, stock[0x8C0][2])
            vals = {r: get(r) for r in s8}
            same = [r for r in s8 if vals[r] == s8[r]]
            cam[folder] = {"window": window(vals), "registers_equal_to_stock_0x8c0": len(same), "of": len(s8),
                           "registers_that_differ": {str(r): [s8[r], vals[r]] for r in sorted(s8) if vals[r] != s8[r]}}
            print(f"camera {folder}: window registers {window(vals)}; {len(same)} of {len(s8)} registers equal stock 0x8c0")
        m = cam["02_after_patch_movie"]
        assert m["window"] == window(s8), "the tester's camera did not hold the stock window after design v1"
        assert not set(m["registers_that_differ"]) & {str(r) for r in WINDOW_REGS}
        res["camera_2026-11-25_pal"] = cam
        res["camera_reading"] = ("after design v1 the sensor's window registers were the stock ones (3348 rows from row 406) while the stored "
                                 "record said 3968 rows from row 96; registers that differ from the matrix are ones the camera rewrites while running")
    else:
        print("no camera dump folder: the comparison with a real camera is skipped")
    out = ROOT / "evidence/fx30/sensor/sensor_regs_fx30_emu.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
    print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
