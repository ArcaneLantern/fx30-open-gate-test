"""The edit-list start of a normal recording (libmpr.so 6.02, the writer set-up 0x11f030), stock against ogfile57r300m1_v3, in Unicorn.

F982 changed 0x118004 in 0x117da8; on the camera that changed nothing (F986: C0556 still starts one frame in), because a normal recording
fills the MP4 request in 0x11f030, which calls the same track builder 0x222b18. There the request's +0x10 (the edit list's start in frames:
media_time = frame duration x it, 0x226818) starts at 0 (0x11f44c) and is set at 0x11f4ac-0x11f4e4 from the format's entry in
mpr::pconv::m_vpcSt (0x2e9080, 7 words a comb: +0 codec 0 AVC / 1 HEVC, ..., +0x18 intra flag) and a flag at [x21+4]:
  intra flag set             -> 0
  [x21+4] set                -> HEVC 0, AVC 1
  otherwise                  -> AVC 1; HEVC 2 for frame-rate codes 4 to 11 (50p and up), else 1   (`csel w0, w1, w0, ls` at 0x11f4e0)
The design changes 0x11f4e0 to `mov w0, #0`: HEVC 0, AVC unchanged. AVC keeps its one frame because its encoder gives every picture a
one-frame composition offset even without B pictures (C0557: ctts 1001 everywhere), which that frame cancels.

This runs 0x11f4ac..0x11f4e8 (and 0x11fe5c..0x11fe67 where it branches) for every comb, frame-rate code 0-11 and both values of [x21+4],
reads what is stored at [x29+0xb40], and writes evidence/pipeline/ogfile57r300m1_v3_elst_emu.json.
Run with the Python that has Unicorn:  C:\\Python313\\python.exe -B build/emu_elst_site_v3.py
  --build fx2_101   (2026-11-27, the FX2's 5.7K port) the FX2 1.01's writer set-up: the same instructions at 0x11e3d8..0x11e413 (and the AVC
                    branch 0x11ed74..0x11ed7f), the slot [x29+0xca8] (stored 0 first at 0x11e378), m_vpcSt 0x2e3898 (its GOT entry 0x2fcd80
                    resolves to _ZN3mpr5pconv7m_vpcStE), against ogfile57r300m1_fx2_v3 (v4 has the same site); writes
                    evidence/fx2/ogfile57r300m1_fx2_elst_emu.json
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

START, END, SITE = 0x11F4AC, 0x11F4E8, 0x11F4E0
TABLE = 0x2E9080                                     # mpr::pconv::m_vpcSt (GOT 0x301d98)
CTX, FRAME = 0x10000000, 0x10100000
PAGE, SLOT = 0x11F000, 0xB40                         # the code page the block and its AVC branch lie in; the slot at [x29 + SLOT]
BUILD, DESIGN, DST = "a7iv_602", "ogfile57r300m1_v3", "evidence/pipeline/ogfile57r300m1_v3_elst_emu.json"
BUILDS = {"fx2_101": {"start": 0x11E3D8, "end": 0x11E414, "site": 0x11E40C, "table": 0x2E3898, "page": 0x11E000, "slot": 0xCA8,
                      "design": "ogfile57r300m1_fx2_v3", "dst": "evidence/fx2/ogfile57r300m1_fx2_elst_emu.json"},
          # 2026-11-28, the FX30's 5.7K step: the same block in the FX30 6.01's writer set-up (site 0x11d5e4; the AVC branch at 0x11df28, same page)
          "fx30_601": {"start": 0x11D5B0, "end": 0x11D5EC, "site": 0x11D5E4, "table": 0x2E0BB0, "page": 0x11D000, "slot": 0xC30,
                       "design": "ogfile57r300m1_fx30_v3", "dst": "evidence/fx30/encoder/ogfile57r300m1_fx30_elst_emu.json"}}


def run(code_page, table, comb, rate, flag4):
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(PAGE, 0x1000)
    uc.mem_write(PAGE, code_page)
    uc.mem_map(TABLE & ~0xFFF, 0x2000)
    uc.mem_write(TABLE, table)
    uc.mem_map(CTX, 0x1000)
    uc.mem_map(FRAME, 0x2000)
    uc.mem_write(CTX + 4, struct.pack("<I", flag4))
    uc.mem_write(FRAME + SLOT, struct.pack("<I", 0))         # 0x11f44c stores 0 there first
    uc.reg_write(R.UC_ARM64_REG_X0, comb * 0x1C)             # x0 = comb x 0x1c (0x11f48c), x2 = the table, x3 = its entry (0x11f49c)
    uc.reg_write(R.UC_ARM64_REG_X2, TABLE)
    uc.reg_write(R.UC_ARM64_REG_X3, TABLE + comb * 0x1C)
    uc.reg_write(R.UC_ARM64_REG_X1, rate)                    # w1 = the frame-rate code ([x21,#0x11c], 0x11f4a0)
    uc.reg_write(R.UC_ARM64_REG_X21, CTX)
    uc.reg_write(R.UC_ARM64_REG_X20, CTX)                    # the FX30 6.01's compile keeps the context in x20 (ldr w3, [x20, #4]); the others do not read x20 here
    uc.reg_write(R.UC_ARM64_REG_X29, FRAME)
    uc.emu_start(START, END, count=64)
    return struct.unpack("<I", uc.mem_read(FRAME + SLOT, 4))[0]


def main():
    global START, END, SITE, TABLE, PAGE, SLOT, BUILD, DESIGN, DST
    if "--build" in sys.argv:                            # 2026-11-27: the FX2 1.01
        BUILD = sys.argv[sys.argv.index("--build") + 1]
        b = BUILDS[BUILD]
        START, END, SITE, TABLE, PAGE, SLOT, DESIGN, DST = b["start"], b["end"], b["site"], b["table"], b["page"], b["slot"], b["design"], b["dst"]
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    design = json.loads((ROOT / "modding/designs" / f"{DESIGN}.json").read_text(encoding="utf8"))
    site, = [p for p in design["patches"] if p["binary"] == "libmpr.so" and p["code"]]
    assert int(site["file_off"], 16) == SITE and bytes.fromhex(site["old"]) == lm[SITE:SITE + 4]
    stock = lm[PAGE:PAGE + 0x1000]
    changed = bytearray(stock)
    changed[SITE - PAGE:SITE - PAGE + 4] = bytes.fromhex(site["new"])
    table = lm[TABLE:TABLE + 14 * 0x1C]
    rows = []
    for comb in range(14):
        codec, intra = struct.unpack_from("<I", table, comb * 0x1C)[0], struct.unpack_from("<I", table, comb * 0x1C + 0x18)[0]
        for flag4 in (0, 1):
            for rate in range(12):
                s, d = run(stock, table, comb, rate, flag4), run(bytes(changed), table, comb, rate, flag4)
                rows.append({"comb": comb, "codec": "HEVC" if codec == 1 else "AVC", "intra_flag": intra, "x21_plus_4": flag4, "rate_code": rate,
                             "stock_frames": s, "design_frames": d})
    for r in rows:
        if r["intra_flag"] or r["x21_plus_4"]:
            assert r["design_frames"] == r["stock_frames"], r
        elif r["codec"] == "AVC":
            assert r["stock_frames"] == r["design_frames"] == 1, r
        else:
            assert r["stock_frames"] == (2 if 4 <= r["rate_code"] <= 11 else 1) and r["design_frames"] == 0, r
    # the formats of the 5.7K state at 23.98p (rate code 0) and 25p (2): what the camera wrote (C0549, C0554, C0556 HEVC; C0553, C0557 AVC)
    used = {c: [r for r in rows if r["comb"] == c and r["x21_plus_4"] == 0 and r["rate_code"] in (0, 2)] for c in (0, 2, 5, 7)}
    assert all(r["stock_frames"] == 1 for v in used.values() for r in v)
    about = ("libmpr.so 0x11f4ac..0x11f4e7 (and 0x11fe5c..0x11fe67) run in Unicorn for every comb, frame-rate code and value of [x21+4]; "
             "the word stored at [x29+0xb40] is the MP4 request's +0x10, the video edit list's start in frames. Generated by build/emu_elst_site_v3.py.")
    if BUILD != "a7iv_602":
        about = ("FX2 1.01 libmpr.so %#x..%#x (and the AVC branch 0x11ed74..0x11ed7f) run in Unicorn for every comb, frame-rate code and value of "
                 "[x21+4]; the word stored at [x29+%#x] is the MP4 request's +0x10, the video edit list's start in frames. Design %s. Generated by "
                 "build/emu_elst_site_v3.py --build %s." % (START, END - 1, SLOT, DESIGN, BUILD))
    out = {"about": about,
           "site": hex(SITE), "stock": "csel w0, w1, w0, ls", "design": "mov w0, #0", "table": "mpr::pconv::m_vpcSt at %#x" % TABLE,
           "the_5_7k_formats_at_23_98p_and_25p": {"comb 0 AVC 4:2:0": "1 -> 1", "comb 2 AVC 4:2:2": "1 -> 1", "comb 5 HEVC 4:2:0": "1 -> 0", "comb 7 HEVC 4:2:2": "1 -> 0"},
           "rows": rows}
    (ROOT / DST).write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    for c, v in used.items():
        print("comb %d (%s): stock %s, design %s" % (c, v[0]["codec"], sorted({r["stock_frames"] for r in v}), sorted({r["design_frames"] for r in v})))
    print(len(rows), "cases: HEVC -> 0 on the normal path; AVC, intra formats and the [x21+4] path unchanged")


if __name__ == "__main__":
    main()
