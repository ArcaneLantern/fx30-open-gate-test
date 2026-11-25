"""Emulate the FX30 6.01 rear-screen layout pieces, stock and with lcd32dsq_fx30_v1 applied, in Unicorn on the FX30's own code.

  work\\venv\\Scripts\\python.exe -I -B build\\emu_lcd_fx30.py [--save]   (needs Unicorn; else C:\\Python313\\python.exe -B -P)
  --save writes evidence/fx30/screen/lcd32dsq_fx30_v1_emu.json

The FX3 kit's emulation (build/emu_lcd_fx3.py) ported: the same functions at the FX30's addresses (cpapp-b.bin 6.01, loaded at 0x108000),
each called the way the automatic layout 0x1e3114 calls it:
  0x1e2ce8  fit mode (panel code, picture aspect code)
  0x1e3024  picture ratio: (_, w | h << 16, panel code, aspect, [fit, out])               -> out = x, y, w, h
  0x1e2f10  de-squeeze:    (_, w | h << 16, panel code, aspect, [fit, out, accessor, device]); the code byte comes from the accessor's
            slot 0x758 (stubbed: a pointer to the code), slot 0x698 only for device 4 (HDMI; not run)
  0x663ada  input crop for 2.0x: (crop rect, frame info, device data); 0x677744 (de-squeeze active) -> 1, 0x679f18 -> 0,
            0x67a020 -> the path flag (0 or 1), slot 0x758 -> the code
  0x128438  frame check (focus frames): 0x5dd2d2 -> 0, 0x5eab7e -> output kind (0 rear, 2 second output), 0x5dd42e -> the live-view
            rectangle (y0, y1, x0, x1) and the output size, 0x5dd6ba -> table row; model aspect 4 (the tables' 16:9 column)
Panels: 1024 x 768 (4:3: the FX30's rear monitor, 2,359,296 dots = 1024 x 768 x 3; panel code 0, frame row 0), 800 x 600 (4:3, the FX3's)
and 720 x 480 (3:2, panel code 1, frame row 1: in case the FX30's type byte says 3). Picture aspect 2 (16:9), the open-gate live view.
The 800 x 600 and 720 x 480 results must equal the FX3 run's (evidence/fx3/lcd32dsq_fx3_v1_emu.json) case for case: the code is the same.
Every expected value is asserted. Read-only apart from the evidence file.
"""
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn import arm_const as A

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

B = 0x108000
FX = locate_file.locate("fx30_601", "cpapp-b.bin").read_bytes()
DESIGN = json.loads((ROOT / "modding/designs/lcd32dsq_fx30_v1.json").read_text(encoding="utf8"))
FX3_EMU = json.loads((ROOT / "evidence/fx3/lcd32dsq_fx3_v1_emu.json").read_text(encoding="utf8"))
RET, STK, OBJ, STUBS = 0x2410000, 0x2300000, 0x2440000, 0x2480000
FIT, RATIO, DSQ, CROP, CHECK = 0x1E2CE8, 0x1E3024, 0x1E2F10, 0x663ADA, 0x128438
ACTIVE, CROP_A, CROP_PATH = 0x677744, 0x679F18, 0x67A020
CK_A, CK_KIND, CK_LIVE, CK_ROW = 0x5DD2D2, 0x5EAB7E, 0x5DD42E, 0x5DD6BA
PANELS = {"4:3 1024x768": (1024, 768, 0, 0), "4:3": (800, 600, 0, 0), "3:2": (720, 480, 1, 1)}   # w, h, panel code, frame-table row


class Cp:
    def __init__(self, patched):
        img = bytearray(FX)
        if patched:
            for s in DESIGN["sites"]:
                a = int(s["ram_address"], 16)
                assert img[a - B:a - B + 4] == bytes.fromhex(s["old"])
                img[a - B:a - B + 4] = bytes.fromhex(s["new"])
            for g in DESIGN["guards"]:
                a = int(g["ram_address"], 16)
                assert img[a - B:a - B + len(g["bytes"]) // 2] == bytes.fromhex(g["bytes"])
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        try:
            uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_A15)
        except Exception:
            pass
        uc.mem_map(0x100000, 0x2500000)
        uc.mem_write(B, bytes(img))
        uc.reg_write(A.UC_ARM_REG_C1_C0_2, uc.reg_read(A.UC_ARM_REG_C1_C0_2) | (0xF << 20))
        uc.reg_write(A.UC_ARM_REG_FPEXC, 0x40000000)
        self.stubs, self.log = {}, []
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, lambda u, acc, addr, sz, v, _: self.log.append(f"unmapped {addr:#x} pc={u.reg_read(A.UC_ARM_REG_PC):#x}") or False)

    def stub(self, addr, fn):
        """fn(uc) -> r0; the stubbed function returns to LR at once"""
        if addr not in self.stubs:
            self.uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, _: self._run_stub(ad), begin=addr, end=addr)
        self.stubs[addr] = fn

    def _run_stub(self, addr):
        u = self.uc
        r0 = self.stubs[addr](u)
        if r0 is not None:
            u.reg_write(A.UC_ARM_REG_R0, r0 & 0xFFFFFFFF)
        u.reg_write(A.UC_ARM_REG_PC, u.reg_read(A.UC_ARM_REG_LR))

    def call(self, fn, regs, stack=()):
        u = self.uc
        sp = STK - 0x800
        for i, v in enumerate(stack):
            u.mem_write(sp + 4 * i, struct.pack("<I", v & 0xFFFFFFFF))
        for r, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), regs):
            u.reg_write(r, v & 0xFFFFFFFF)
        u.reg_write(A.UC_ARM_REG_SP, sp)
        u.reg_write(A.UC_ARM_REG_LR, RET | 1)
        u.emu_start(fn | 1, RET, count=100000)
        assert not self.log, self.log
        return u.reg_read(A.UC_ARM_REG_R0)

    def rect(self, a):
        return list(struct.unpack("<4H", bytes(self.uc.mem_read(a, 8))))

    def accessor(self, code):
        u, vt, ptr = self.uc, OBJ + 0x1000, OBJ + 0x3000
        u.mem_write(OBJ, struct.pack("<I", vt))
        u.mem_write(ptr, bytes([code, 1]))
        for slot, fn in ((0x758, lambda uc: ptr), (0x698, lambda uc: 0)):
            a = STUBS + slot * 4
            u.mem_write(a, b"\x70\x47")
            u.mem_write(vt + slot, struct.pack("<I", a | 1))
            self.stub(a, fn)
        return OBJ

    def fit(self, panel, aspect):
        return self.call(FIT, (panel, aspect))

    def ratio(self, w, h, panel, aspect):
        out = OBJ + 0x8000
        self.uc.mem_write(out, bytes(8))
        self.call(RATIO, (0, w | h << 16, panel, aspect), (self.fit(panel, aspect), out))
        return self.rect(out)

    def desqueeze(self, w, h, panel, aspect, code, device=1):
        out = OBJ + 0x8000
        self.uc.mem_write(out, bytes(8))
        acc = self.accessor(code)
        self.call(DSQ, (0, w | h << 16, panel, aspect), (self.fit(panel, aspect), out, acc, device))
        return self.rect(out)

    def crop(self, code, path, full_w=1920, h=1080, x=0, aspect=2):
        r, f = OBJ + 0x9000, OBJ + 0x9100
        self.uc.mem_write(r, bytes(0x20))
        self.uc.mem_write(r + 8, struct.pack("<H", full_w))
        self.uc.mem_write(r + 0xC, struct.pack("<HHHH", x, 0, full_w - 2 * x, h))
        self.uc.mem_write(f, bytes(0x20))
        self.uc.mem_write(f + 0x1E, bytes([aspect]))
        acc = self.accessor(code)
        self.stub(ACTIVE, lambda uc: 1)
        self.stub(CROP_A, lambda uc: 0)
        self.stub(CROP_PATH, lambda uc: path)
        self.call(CROP, (r, f, acc))
        x_, _, w_, h_ = struct.unpack("<4H", bytes(self.uc.mem_read(r + 0xC, 8)))
        return [x_, w_, h_]

    def frame_check(self, live, out_w, out_h, kind, row_sel, model_aspect=4):
        m = OBJ + 0x10000
        u = self.uc
        u.mem_write(m, bytes(0x2000))
        u.mem_write(m + 0x1C90, struct.pack("<I", model_aspect))
        x, y, w, h = live

        def lv(uc):
            sp = uc.reg_read(A.UC_ARM_REG_SP)
            p_h = struct.unpack("<I", bytes(uc.mem_read(sp, 4)))[0]
            uc.mem_write(uc.reg_read(A.UC_ARM_REG_R1), struct.pack("<4i", y, y + h, x, x + w))
            uc.mem_write(uc.reg_read(A.UC_ARM_REG_R3), struct.pack("<H", out_w))
            uc.mem_write(p_h, struct.pack("<H", out_h))
            return 1
        self.stub(CK_A, lambda uc: 0)
        self.stub(CK_KIND, lambda uc: kind)
        self.stub(CK_LIVE, lv)
        self.stub(CK_ROW, lambda uc: row_sel)
        return self.call(CHECK, (m,))


def fx3_case(what, panel=None):
    hits = [c for c in FX3_EMU["cases"] if c["what"] == what and c.get("panel") == panel]
    assert len(hits) == 1, (what, panel, len(hits))
    return hits[0]


def run():
    st, pa = Cp(False), Cp(True)
    res = {"design": DESIGN["design"], "image_sha256": DESIGN["artifact_sha256"], "cases": [], "equal_to_the_fx3_run": 0}
    case = lambda **k: res["cases"].append(k)

    def same_as_fx3(c, keys):
        nonlocal res
        if c.get("panel") in ("4:3", "3:2"):
            ref = fx3_case(c["what"], c["panel"])
            assert all(ref[k] == c[k] for k in keys), (c, ref)
            res["equal_to_the_fx3_run"] += 1
    # ---- fit mode: a 16:9 picture is letterboxed on both panel shapes, stock and patched
    for name, (w, h, pc, _) in PANELS.items():
        assert st.fit(pc, 2) == pa.fit(pc, 2) == 3
        c = dict(what="fit mode, 16:9 picture", panel=name, stock=3, patched=3)
        case(**c)
        same_as_fx3(c, ("stock", "patched"))
    # ---- the picture ratio (de-squeeze off)
    live = {}
    for name, (w, h, pc, _) in PANELS.items():
        s, p = st.ratio(w, h, pc, 2), pa.ratio(w, h, pc, 2)
        assert abs(s[2] / s[3] - 16 / 9) < 0.01 and s[2] == w and s[1] * 2 + s[3] in (h, h - 1, h + 1), (name, s)
        shown = p[2] / p[3]
        if pc == 0:
            assert p[2] == w and abs(shown - 1.5) < 0.01 and abs(p[1] * 2 + p[3] - h) <= 1, (name, p)
        else:
            assert p == [0, 0, w, h], (name, p)                           # 3:2 panel: the whole panel
        live[name] = (s, p)
        c = dict(what="live view, de-squeeze off, 16:9 picture (the open-gate frame)", panel=name, stock=s, patched=p, shown_aspect=round(shown, 4))
        case(**c)
        same_as_fx3(c, ("stock", "patched", "shown_aspect"))
        for asp in (0, 1, 3, 4, 5):
            assert st.ratio(w, h, pc, asp) == pa.ratio(w, h, pc, asp), (name, asp)
        case(what="live view, other picture aspect codes 0, 1, 3, 4, 5", panel=name, stock_equals_patched=True)
    # ---- the built-in de-squeeze
    factors = {1: 1.3, 2: 1.5, 3: 1.65, 4: 2.0}
    for name, (w, h, pc, _) in PANELS.items():
        assert st.desqueeze(w, h, pc, 2, 0) == pa.desqueeze(w, h, pc, 2, 0) == [0, 0, w, h]
        for code, fac in factors.items():
            s, p = st.desqueeze(w, h, pc, 2, code), pa.desqueeze(w, h, pc, 2, code)
            stock_target = 16 / 9 * fac if code != 4 else 4 / 3 * 2
            target = 1.5 * fac
            shown_s, shown_p = s[2] / s[3], p[2] / p[3]
            assert abs(shown_p / target - 1) < 0.012, (name, code, shown_p, target)
            assert abs(shown_s / stock_target - 1) < 0.012, (name, code, shown_s, stock_target)
            assert p[0] == 0 and p[2] == w and abs(2 * p[1] + p[3] - h) <= 1, (name, code, p)
            for asp in (5, 0, 1):
                a_s, a_p = st.desqueeze(w, h, pc, asp, code), pa.desqueeze(w, h, pc, asp, code)
                if code != 4:
                    assert a_s == a_p, (name, code, asp)
                else:
                    assert a_s[3] == ((w * 3 + 16) // 8) & ~3 and a_p[3] == ((w + 6) // 3) & ~3, (name, asp, a_s, a_p)
            c = dict(what=f"de-squeeze code {code} ({fac}x), 16:9 picture", panel=name, stock=s, patched=p,
                     shown_stock=round(shown_s, 4), shown_patched=round(shown_p, 4), right_for_the_3_2_frame=round(target, 4),
                     stock_with_the_3_2_frame_is_off_by=round(shown_s / target, 4))
            case(**c)
            same_as_fx3(c, ("stock", "patched", "shown_stock", "shown_patched"))
    # ---- the 2.0x input crop
    for path in (0, 1):
        s, p = st.crop(4, path), pa.crop(4, path)
        assert s == [240, 1440, 1080] and p == [0, 1920, 1080], (path, s, p)
        c = dict(what=f"2.0x input crop, path {path}, 1920 x 1080 live view", stock=s, patched=p)
        case(**c)
        ref = fx3_case(c["what"])
        assert (ref["stock"], ref["patched"]) == (s, p)
        res["equal_to_the_fx3_run"] += 1
        for code in (1, 2, 3):
            assert st.crop(code, path) == pa.crop(code, path) == [0, 1920, 1080]
    s, p = st.crop(4, 1, x=96), pa.crop(4, 1, x=96)
    assert s != [96, 1728, 1080] and p == [96, 1728, 1080], (s, p)
    case(what="2.0x input crop, path 1 with an existing offset 96", stock=s, patched=p)
    # ---- the frame check
    for name, (w, h, pc, row) in PANELS.items():
        s_live, p_live = live[name]
        ok = lambda cp, lv_, kind=0, rs=row: cp.frame_check(lv_, w, h, kind, rs)
        r = {"stock_tables_stock_view": ok(st, s_live), "patched_tables_patched_view": ok(pa, p_live),
             "stock_tables_patched_view": ok(st, p_live), "patched_tables_stock_view": ok(pa, s_live)}
        assert r == {"stock_tables_stock_view": 1, "patched_tables_patched_view": 1, "stock_tables_patched_view": 0, "patched_tables_stock_view": 0}, (name, r)
        c = dict(what=f"frame check, rear output, table row {row}", panel=name, **r)
        case(**c)
        same_as_fx3(c, tuple(r))
        dsq = {code: (ok(st, st.desqueeze(w, h, pc, 2, code)), ok(pa, pa.desqueeze(w, h, pc, 2, code))) for code in factors}
        assert all(a == b == 0 for a, b in dsq.values()), dsq
        case(what="frame check while de-squeeze is on (stock and patched alike)", panel=name, results={str(k): list(v) for k, v in dsq.items()})
    for (w, h) in ((800, 600), (1024, 768)):                                # second output (row 2)
        s_live, p_live = st.ratio(w, h, 0, 2), pa.ratio(w, h, 0, 2)
        s2, st2 = pa.frame_check(p_live, w, h, 2, 0), st.frame_check(s_live, w, h, 2, 0)
        assert s2 == 1 and st2 == 1
        case(what=f"frame check, second output (row 2), {w} x {h}", stock_view_stock=st2, patched_view_patched=s2)
    return res


if __name__ == "__main__":
    res = run()
    for c in res["cases"]:
        print(json.dumps(c))
    print(f"{len(res['cases'])} cases as expected; {res['equal_to_the_fx3_run']} equal to the FX3 7.02 run case for case")
    if "--save" in sys.argv:
        out = ROOT / "evidence" / "fx30" / "screen" / "lcd32dsq_fx30_v1_emu.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
        print("wrote", out)
