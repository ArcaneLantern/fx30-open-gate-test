"""Run the built FX30 6.01 write libraries (build_fx30_write.sh) in Unicorn against a model camera. Offline; no camera. (FX30 port, 2026-11-26)

  C:\\Python313\\python.exe -B emu_fx30_write.py

helper_fx2/emu_fx2_write.py with this camera's models and steps:
  - coprocessor transfers must be whole 64-byte lines to or from the allocated buffer; a transfer TOWARDS the coprocessor may change only
    bytes of a listed site, and only to that site's stock or new bytes (of the variant in use);
  - L5/L6: the sensor object 0x13bd0d8 -> control -> +0x690 -> parameter object {vtable, 31, ids, 0, records} -> the 0x160-byte stored
    records; the five modes the design changes (0x820, 0x880, 0x890, 0x8c0, 0x8d0) hold the FX30's emulated stock records of one timing
    system (build/emu_drvparam.py fx30_601 with the 60 Hz or the 50 Hz table), the others a filler. readcheck.c's MULTI_REC path must
    pick the variant every record holds and refuse a camera whose records agree on none. Design ogsq_fx30_v2: nine table/record sites,
    one of them the register matrix's rows of the sensor's window registers (seven bytes of column 1 change); a camera that still holds
    kit v1's sensor design (ogsq_fx30_v1) must be refused;
  - L16/L17, S16/S17: the movie size table as the FX30's set-up fills it (build/emu_size_table.py fx30_601), and the loaded image for the
    screen words;
  - L19/L20, N19/N20: av-cam.bin at its physical address and libmpr.so in the process's own mapping;
  - P29/P30: emu_fx30_playback.py (the FX3 kit's playback cases on the FX30's file).
Cases per library: apply on stock, apply again (nothing to do), put back (byte for byte), a site holding foreign bytes, a lost write
(undo), a guard wrong. Safety: the FX3, FX2, A7C II and A7 IV kits' libraries of the same steps write nothing on an FX30.
"""
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "build"))
import emu_built as E  # noqa: E402
from unicorn import arm64_const as R  # noqa: E402
import emu_size_table  # noqa: E402
import emu_fx30_playback  # noqa: E402

BASE, CP_HI = 0x108000, 0x10000000
DES = ROOT / "modding/designs"
IMAGER, CTRL, OBJ, CTRL_DRVPARAM = 0x13BD0D8, 0x1500000, 0x1500800, 0x690
IDS, RECS, REC, COUNT, VTABLE = 0xD10D68, 0x20D93A4, 0x160, 31, 0xD12078
LM_AT = 0x7F82D15000
RESULT = E.RESULT
DEFAULT_DESIGN = E.DESIGN


def ex(rel, build="fx30_601"):
    return (ROOT / f"work/extracted/{build}/0700_part_image/dev" / rel).read_bytes()


def design(name):
    return json.loads((DES / f"{name}.json").read_text(encoding="utf8"))


def lib(name, folder="helper_fx30", prefix="fx30"):
    return (HERE.parent / folder / f"libJit_{prefix}_{name}.so").read_bytes()


class Mem:
    """Coprocessor memory: the image at 0x108000, zeros elsewhere, with what the model camera adds."""

    def __init__(self, image):
        self.pages, self.image = {}, image

    def page(self, a):
        a &= ~0xFFF
        if a not in self.pages:
            p = bytearray(4096)
            if BASE <= a < BASE + len(self.image):
                chunk = self.image[a - BASE:a - BASE + 4096]
                p[:len(chunk)] = chunk
            self.pages[a] = p
        return self.pages[a]

    def read(self, a, n):
        return bytes(self.page(a + k)[(a + k) & 0xFFF] for k in range(n))

    def write(self, a, data):
        for k, v in enumerate(data):
            self.page(a + k)[(a + k) & 0xFFF] = v

    def snapshot(self):
        return {a: bytes(p) for a, p in self.pages.items()}


class Run(E.Run):
    """emu_fx2_write.py's run: every import is modelled here, against Mem."""

    def __init__(self, libbytes, files, dirs, mem, allowed, lose=None):
        saved, E.DESIGN = E.DESIGN, DEFAULT_DESIGN
        super().__init__(libbytes, 5, files, dirs, cp=b"")
        E.DESIGN = saved
        self.mem, self.allowed, self.lose, self.n_writes = mem, allowed, lose, 0

    def go(self):
        self.uc.reg_write(R.UC_ARM64_REG_SP, E.STACK - 0x1000)
        self.uc.reg_write(R.UC_ARM64_REG_X30, E.RET)
        self.uc.emu_start(self.ctor, E.RET, count=2_000_000_000)
        if not self.bad and self.uc.reg_read(R.UC_ARM64_REG_PC) != E.RET:
            self.bad = "the constructor did not return"
        return self

    def on_import(self, uc, address, size, _):
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        name, ret = self.imports.get(address), 0
        if name == "_Z9dmm_allocjPj":
            uc.mem_write(x(1), struct.pack("<I", E.BUF_HANDLE))
            ret = self.buf
        elif name == "_Z8dmm_freej":
            pass
        elif name == "sen_dma_transfer":
            d, src, dst, n = x(0) & 0xFFFFFFFF, x(1), x(2), x(3) & 0xFFFFFFFF
            cp = src if d == 0 else dst
            if d not in (0, 1) or (dst if d == 0 else src) != self.buf or cp & 63 or n & 63 or not 0 < n <= 4096 or cp < BASE or cp + n > CP_HI:
                self.bad = "a transfer that is not whole lines to or from the buffer: dir %d src %#x dst %#x size %d" % (d, src, dst, n)
                uc.emu_stop()
                return
            va = next(v for v, off in self.map_phys.items() if v in self.maps and off <= self.buf < off + self.maps[v]) + self.buf % 4096
            if d == 0:
                uc.mem_write(va, self.mem.read(cp, n))
            else:
                data, now = bytes(uc.mem_read(va, n)), self.mem.read(cp, n)
                for k in range(n):
                    if data[k] != now[k] and data[k] not in self.allowed.get(cp + k, ()):
                        self.bad = "a write that changes %#x to %#x, which is not a listed site's stock or new byte" % (cp + k, data[k])
                        uc.emu_stop()
                        return
                self.n_writes += 1
                if self.lose != self.n_writes:
                    self.mem.write(cp, data)
        else:
            self.bad = "call of an unexpected import %r" % name
            uc.emu_stop()
            return
        uc.reg_write(R.UC_ARM64_REG_X0, ret)
        uc.reg_write(R.UC_ARM64_REG_PC, uc.reg_read(R.UC_ARM64_REG_X30))


def main():
    fail = []
    ok = lambda cond, text: (print(("PASS  " if cond else "FAIL  ") + text), fail.append(text) if not cond else None)
    image = ex("nflasha8/cpapp-b.bin")
    files = E.tree()
    files["/dev/mem"] = b""
    dirs = {"/tmp_wbshd", "/sys/module/liro/parameters", "/proc/driver/pcie"}

    def go(libbytes, mem, allowed, **kw):
        r = Run(libbytes, files, dirs, mem, allowed, **kw).go()
        return r, r.writes.get(RESULT, b"").decode("utf8", "replace")

    def changed_only(mem, before, allowed):
        for a, p in mem.pages.items():
            b = before.get(a)
            if b is None:
                b = image[a - BASE:a - BASE + 4096].ljust(4096, b"\0") if BASE <= a < BASE + len(image) else bytes(4096)
            if any(p[k] != b[k] and (a + k) not in allowed for k in range(4096)):
                return False
        return True

    # ---- L5 / L6: the 9 table/record sites and the five stored records, NTSC or PAL
    d = design("ogsq_fx30_v2")
    sensor = d["summary"]["sensor"]
    cells = {int(a, 16): sensor["registers"][r] for r, a in sensor["cells"].items()}      # matrix byte -> [stock, new]
    srs = d["stored_records"]
    recs = {s: {int(m, 16): (RECS + v["index"] * REC, bytes.fromhex(v[s]["stock"]), bytes.fromhex(v[s]["design"])) for m, v in srs.items()} for s in ("ntsc", "pal")}
    table_allowed = {}
    for p in d["patches"]:
        a = int(p["addr"], 16)
        for k, (o, n) in enumerate(zip(bytes.fromhex(p["old"]), bytes.fromhex(p["new"]))):
            if o != n:
                table_allowed[a + k] = (o, n)

    def allowed_for(system):
        al = dict(table_allowed)
        for a, st, nw in recs[system].values():
            for k in range(REC):
                if st[k] != nw[k]:
                    al[a + k] = (st[k], nw[k])
        return al

    def camera(system="ntsc", img=image, imager=IMAGER, mixed=None):
        m = Mem(img)
        m.write(imager, struct.pack("<I", CTRL))
        m.write(CTRL + CTRL_DRVPARAM, struct.pack("<I", OBJ))
        m.write(OBJ, struct.pack("<6I", VTABLE, COUNT, IDS, 0, RECS, 0xD10DE4))
        for i in range(COUNT):
            m.write(RECS + i * REC, bytes([i]) * REC)
        for mode, (a, st, _) in recs[system].items():
            m.write(a, recs[mixed][mode][1] if mixed and mode == 0x8C0 else st)
        return m

    def state(mem, system):
        vals = [(mem.read(a, 1)[0], pr) for a, pr in allowed_for(system).items()]
        return "stock" if all(v == pr[0] for v, pr in vals) else "new" if all(v == pr[1] for v, pr in vals) else "mixed"
    L5, L6 = lib("L5"), lib("L6")
    for system in ("ntsc", "pal"):
        al = allowed_for(system)
        mem = camera(system)
        before = mem.snapshot()
        r, t = go(L5, mem, al)
        name = "NTSC (60 Hz)" if system == "ntsc" else "PAL (50 Hz)"
        ok(not r.bad and "DONE: all 14 sites hold the target bytes (apply)" in t and f"the stored records are the {name} variant" in t
           and state(mem, system) == "new" and changed_only(mem, before, al),
           f"L5 on a stock FX30 ({system}): 9 sites and the five stored records new ({name} variant), nothing else changed ({r.n_writes} line writes)")
        n_lines = r.n_writes
        ok(len(cells) == 7 and all(mem.read(a, 1)[0] == new for a, (_, new) in cells.items())
           and (mem.read(min(cells), 1)[0] | mem.read(min(cells) + 20, 1)[0] << 8) == d["summary"]["window_row"] + sensor["row_bias"],
           f"L5 ({system}): the register matrix's column 1 holds the sensor's new window (registers 6/7 = row 94 + 81, 8/9 = 1990 line pairs, 14, 16, 25)")
        r, t = go(L5, mem, al)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, f"L5 again ({system}): nothing to do, no write")
        r, t = go(L6, mem, al)
        ok(not r.bad and "(put back)" in t and "DONE" in t and state(mem, system) == "stock" and changed_only(mem, before, {}),
           f"L6 ({system}): everything stock again, byte for byte")
        r, t = go(L6, mem, al)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, f"L6 on a stock camera ({system}): nothing to do, no write")
    al = allowed_for("ntsc")
    mem = camera("ntsc", mixed="pal")
    before = mem.snapshot()
    r, t = go(L5, mem, {**al, **allowed_for("pal")})
    ok(not r.bad and r.n_writes == 0 and "hold neither timing variant" in t and changed_only(mem, before, {}),
       "L5 with one record of the PAL variant among NTSC ones: refused, nothing is written")
    mem = camera()
    mem.write(int(d["patches"][0]["addr"], 16) + 6, b"\x55")
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "holds neither the stock nor the new bytes; nothing is written" in t, "L5 with a table site holding other bytes: nothing is written")
    mem = camera()
    a8c0 = recs["ntsc"][0x8C0][0]
    mem.write(a8c0 + 0x66, b"\x00\x10")
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "hold neither timing variant" in t, "L5 with the 0x8c0 record's window height foreign: nothing is written")
    assert n_lines == 14                                    # one write per site: 9 table/record sites by address (the matrix is the 9th), 5 stored records
    for lose in (1, 6, 9, 13, 14):                          # a picture record, a table, the register matrix, stored records (the last one too)
        mem = camera()
        before = mem.snapshot()
        r, t = go(L5, mem, al, lose=lose)
        ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and state(mem, "ntsc") == "stock" and changed_only(mem, before, {}),
           f"L5 with line write {lose} lost: reported, every site put back")
    # ---- variant B of the sensor step (ogsq_fx30_v2b, B5 / B6): the same sites, two values differ per mode (an A/B test on a camera)
    db = design("ogsq_fx30_v2b")
    B5, B6 = lib("B5"), lib("B6")
    recs_b = {s: {int(m, 16): (RECS + v["index"] * REC, bytes.fromhex(v[s]["stock"]), bytes.fromhex(v[s]["design"])) for m, v in db["stored_records"].items()} for s in ("ntsc", "pal")}

    def allowed_b(system):
        al_b = {}
        for p in db["patches"]:
            a = int(p["addr"], 16)
            for k, (o, n) in enumerate(zip(bytes.fromhex(p["old"]), bytes.fromhex(p["new"]))):
                if o != n:
                    al_b[a + k] = (o, n)
        for a, st, nw in recs_b[system].values():
            for k in range(REC):
                if st[k] != nw[k]:
                    al_b[a + k] = (st[k], nw[k])
        return al_b

    def state_b(mem, system):
        vals = [(mem.read(a, 1)[0], pr) for a, pr in allowed_b(system).items()]
        return "stock" if all(v == pr[0] for v, pr in vals) else "new" if all(v == pr[1] for v, pr in vals) else "mixed"

    wrote_nothing = lambda t: "nothing is written" in t and not any(ln.startswith(("DONE: ", "NOTHING TO DO", "NOT DONE: ")) for ln in t.split("\n"))
    differ = sorted(a for a in allowed_b("ntsc") if allowed_b("ntsc")[a] != allowed_for("ntsc").get(a))
    ok(len(differ) == 5 * 2 + 5 * 2 and all(mem_a in allowed_for("ntsc") for mem_a in differ),   # one byte each (121 -> 145, 2014 -> 2020)
       f"variant B differs from the design in {len(differ)} bytes: the first phase-detect row and the read-out length of five table rows and five stored records")
    for system in ("ntsc", "pal"):
        alb = allowed_b(system)
        mem = camera(system)
        before = mem.snapshot()
        r, t = go(B5, mem, alb)
        ok(not r.bad and "DONE: all 14 sites hold the target bytes (apply)" in t and state_b(mem, system) == "new" and changed_only(mem, before, alb)
           and all(mem.read(a, 1)[0] == new for a, (_, new) in cells.items()),
           f"B5 on a stock FX30 ({system}): variant B's 9 sites and five stored records new, the sensor's window registers as the design's, nothing else changed")
        snap_b = mem.snapshot()
        for which, lb in (("L5", L5), ("L6", L6)):
            r, t = go(lb, mem, {**alb, **allowed_for(system)})
            ok(not r.bad and r.n_writes == 0 and wrote_nothing(t) and changed_only(mem, snap_b, {}),
               f"{which} (variant A) on a camera that holds variant B ({system}): nothing is written, and its result reads as NOTHING WRITTEN")
        r, t = go(B5, mem, alb)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, f"B5 again ({system}): nothing to do, no write")
        r, t = go(B6, mem, alb)
        ok(not r.bad and "(put back)" in t and "DONE" in t and state_b(mem, system) == "stock" and changed_only(mem, before, {}),
           f"B6 ({system}): everything stock again, byte for byte")
        # the other way round: variant A in memory, variant B's steps write nothing
        al_a = allowed_for(system)
        r, t = go(L5, mem, al_a)
        ok(not r.bad and state(mem, system) == "new", f"L5 after B6 ({system}): variant A applied (the switch-to-a order)")
        snap_a = mem.snapshot()
        for which, lb in (("B5", B5), ("B6", B6)):
            r, t = go(lb, mem, {**alb, **al_a})
            ok(not r.bad and r.n_writes == 0 and wrote_nothing(t) and changed_only(mem, snap_a, {}),
               f"{which} (variant B) on a camera that holds variant A ({system}): nothing is written")
        r, t = go(L6, mem, al_a)
        r2, t2 = go(B5, mem, alb)
        ok(not r.bad and not r2.bad and "DONE" in t and "DONE: all 14 sites hold the target bytes (apply)" in t2 and state_b(mem, system) == "new",
           f"L6 then B5 ({system}): variant B applied (the switch-to-b order)")
    mem = camera()
    r, t = go(B5, mem, allowed_b("ntsc"), lose=7)
    ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and state_b(mem, "ntsc") == "stock",
       "B5 with the LC span's write lost: reported, every site put back")
    # a camera that still holds kit v1's sensor design (no cold boot since): its tables are neither stock nor v2's
    v1 = design("ogsq_fx30_v1")
    mem = camera()
    for p in v1["patches"]:
        mem.write(int(p["addr"], 16), bytes.fromhex(p["new"]))
    for m, v in v1["stored_records"].items():
        mem.write(RECS + v["index"] * REC, bytes.fromhex(v["ntsc"]["design"]))
    before = mem.snapshot()
    for which, lb in (("L5", L5), ("L6", L6)):
        r, t = go(lb, mem, al)
        ok(not r.bad and r.n_writes == 0 and "nothing is written" in t and changed_only(mem, before, {}),
           f"{which} of kit v2 on a camera that still holds kit v1's sensor design: nothing is written")
    mem = camera()
    mem.write(min(cells), bytes([sensor["registers"]["6"][0] ^ 0x10]))
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "holds neither the stock nor the new bytes; nothing is written" in t,
       "L5 with a sensor-window byte of the matrix holding another value: nothing is written")
    mem = camera()
    mem.write(OBJ + 0x10, bytes(4))
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "a stored record was not found" in t, "L5 with a null records pointer: nothing is written")
    mem = camera()
    mem.write(IDS + 4 * 7, struct.pack("<I", 0x1234))      # 0x8d0 missing from the id table
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "a stored record was not found" in t, "L5 when mode 0x8d0 is not in the id table: nothing is written")
    mem = camera(imager=0x127AB68)                         # the pointer where the FX3 has it, not where the FX30 has it
    mem.write(IMAGER, bytes(4))
    r, t = go(L5, mem, al)
    ok(not r.bad and r.n_writes == 0 and "a stored record was not found" in t, "L5 with the FX30's sensor object empty (the chain at the FX3's address): nothing is written")
    # the other kits' sensor steps on an FX30: they must write nothing (an FX30 owner might run another kit)
    foreign = [("FX3 kit L5 (ogsq_fx3_v1)", HERE.parent / "helper_fx3/libJit_fx3_L5.so", 0x127AB68),
               ("FX2 kit L5 (ogsq_fx2_v1)", HERE.parent / "helper_fx2/libJit_fx2_L5.so", 0x1750860),
               ("A7C II kit level 5 (ogsq_c2_v1)", HERE.parent / "helper_c2/libJit_c2_level5_ogsq_c2_v1.so", 0x18AEB8C),
               ("A7 IV level 5 (ogsq_v3)", HERE.parent / "helper/libJit_level5_ogsq_v3.so", 0x12B9CE0)]
    for label, path, their_imager in foreign:
        if not path.is_file():
            print("NOTE  %s not built: skipped" % label)
            continue
        mem = camera(imager=their_imager)                  # even with its pointer chain made to reach the FX30's real parameter object
        for off in (0x684, 0x698, 0x6AC):
            mem.write(CTRL + off, struct.pack("<I", OBJ))
        before = mem.snapshot()
        r, t = go(path.read_bytes(), mem, {})
        ok(not r.bad and r.n_writes == 0 and changed_only(mem, before, {}), f"{label} on an FX30, its chain led to the FX30's records: nothing is written")

    # ---- L16 / L17 (output size) and S16 / S17 (screen words)
    t_, srows, _ = emu_size_table.table("fx30_601")

    def words_mem():
        m = Mem(image)
        for k, (w, h, mid) in enumerate(srows):
            m.write(t_ + 8 * k, struct.pack("<2HI", w, h, mid))
        return m
    for name, s_apply, s_back in (("outsz2560_fx30_v1", "L16", "L17"), ("lcd32dsq_fx30_v1", "S16", "S17")):
        dw = design(name)
        w_allowed = {}
        for s in dw["sites"]:
            a = int(s["ram_address"], 16)
            for k, (o, n) in enumerate(zip(bytes.fromhex(s["old"]), bytes.fromhex(s["new"]))):
                w_allowed[a + k] = (o, n)
        La, Lb = lib(s_apply), lib(s_back)

        def wstate(mem):
            vals = [(mem.read(a, 1)[0], pr) for a, pr in w_allowed.items()]
            return "stock" if all(v == pr[0] for v, pr in vals) else "new" if all(v == pr[1] for v, pr in vals) else "mixed"
        mem = words_mem()
        before = mem.snapshot()
        r, t = go(La, mem, w_allowed)
        ok(not r.bad and "DONE" in t and wstate(mem) == "new" and changed_only(mem, before, w_allowed),
           f"{s_apply} ({name}) on the model: {len(dw['sites'])} word(s) new, nothing else changed ({r.n_writes} line writes)")
        r, t = go(La, mem, w_allowed)
        ok(not r.bad and "NOTHING TO DO" in t and r.n_writes == 0, f"{s_apply} again: nothing to do")
        r, t = go(Lb, mem, w_allowed)
        ok(not r.bad and "DONE" in t and wstate(mem) == "stock" and changed_only(mem, before, {}), f"{s_back}: stock again, byte for byte")
        bad_guard = None
        for g in dw["guards"]:
            mem = words_mem()
            ga = int(g["ram_address"], 16)
            mem.write(ga, bytes([mem.read(ga, 1)[0] ^ 1]))
            r, t = go(La, mem, w_allowed)
            if r.bad or r.n_writes:
                bad_guard = ga
                break
        ok(bad_guard is None, f"{s_apply} with any one of its {len(dw['guards'])} guards wrong: nothing is written")
        mem = words_mem()
        a0 = int(dw["sites"][0]["ram_address"], 16)
        mem.write(a0, b"\x5a\x5a\x5a\x5a")
        r, t = go(La, mem, w_allowed)
        ok(not r.bad and r.n_writes == 0, f"{s_apply} with its first word holding other bytes: nothing is written")
        mem = words_mem()
        r, t = go(La, mem, w_allowed, lose=1)
        ok(not r.bad and "NOT DONE" in t and wstate(mem) == "stock", f"{s_apply} with the first line write lost: everything put back")
    for label, path in (("FX3 kit S16 (lcd32dsq_fx3_v1)", HERE.parent / "helper_fx3/libJit_fx3_S16.so"),
                        ("FX3 kit L16 (outsz2560_fx3_v1)", HERE.parent / "helper_fx3/libJit_fx3_L16.so"),
                        ("FX2 kit S16 (lcd32dsq_fx2_v1)", HERE.parent / "helper_fx2/libJit_fx2_S16.so"),
                        ("FX2 kit L16 (outsz2560_fx2_v1)", HERE.parent / "helper_fx2/libJit_fx2_L16.so"),
                        ("A7 IV level 16 (outsz2560_v1)", HERE.parent / "helper/libJit_level16_outsz2560_v1.so")):
        if path.is_file():
            mem = words_mem()
            before = mem.snapshot()
            r, t = go(path.read_bytes(), mem, {})
            ok(not r.bad and r.n_writes == 0 and changed_only(mem, before, {}), f"{label} on an FX30: nothing is written")

    # ---- L19 / L20 / N19 / N20: encoder side
    av, lm = ex("nflasha3/av-cam.bin"), ex("nflasha15/lib/libmpr.so")
    av = bytes([0x5A]) * 0x1000 + av[0x1000:]
    phoff, phentsize, phnum = struct.unpack_from("<Q", lm, 0x20)[0], *struct.unpack_from("<HH", lm, 0x36)
    span = next(struct.unpack_from("<IIQQQQQQ", lm, phoff + k * phentsize) for k in range(phnum) if struct.unpack_from("<I", lm, phoff + k * phentsize)[0] == 1)[5]
    lspan = (span + 0xFFF) & ~0xFFF
    lm0 = lm[:span].ljust(lspan, b"\0")
    mfiles = dict(files)
    mfiles["/proc/self/mem"] = b""
    mfiles["/proc/self/maps"] = (b"00400000-00409000 r-xp 00000000 fc:8f 81970                              /usr/bin/im.elf\n"
                                 + b"%x-%x r-xp 00000000 fc:8f 55354                          /usr/lib/libmpr.so\n" % (LM_AT, LM_AT + lspan)
                                 + b"%x-%x ---p %08x fc:8f 55354                          /usr/lib/libmpr.so\n" % (LM_AT + lspan, LM_AT + lspan + 0x10000, lspan)
                                 + b"7f8b936000-7f8b991000 r-xp 00000000 fc:8f 55344                          /usr/lib/libsencore.so\n")
    sts = {}
    for dn in ("ogfile2560_hs_s_fx30_v2", "ogfile2560_hs_s_fx30_v1"):
        fl = design(dn)
        sts[dn] = {"av-cam.bin": [], "libmpr.so": []}
        for p in fl["patches"]:
            sts[dn][p["binary"]].append((int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])))

    def applied(blob, dn, which):
        b = bytearray(blob)
        for o, old, new in sts[dn][which]:
            b[o:o + len(new)] = new
        return bytes(b)

    def mp(step, av_mem, lm_mem, libpath=None, **wrong):
        r = E.Run(libpath.read_bytes() if libpath else lib(step), int(step[1:]), mfiles, dirs, {E.AVCAM_PHYS: av_mem}, own={LM_AT: lm_mem})
        r.kview_fail = False
        r.stale = {E.AVCAM_PHYS + o for o in wrong.get("stale", ())}
        r.pwrite_lost = {LM_AT + o for o in wrong.get("pwrite_lost", ())}
        r.go()
        return r, r.writes.get(RESULT, b"").decode("utf8", "replace"), bytes(r.phys[E.AVCAM_PHYS]), bytes(r.uc.mem_read(LM_AT, lspan))
    V2, V1 = "ogfile2560_hs_s_fx30_v2", "ogfile2560_hs_s_fx30_v1"
    av2, lm2 = applied(av, V2, "av-cam.bin"), applied(lm0, V2, "libmpr.so")
    av1, lm1 = applied(av, V1, "av-cam.bin"), applied(lm0, V1, "libmpr.so")
    ok(av1 == av2 and lm1 != lm2, "the two encoder designs differ only in libmpr.so (the two MP4 header heights)")
    r, t, a, m = mp("L19", av, lm0)
    ok(not r.bad and a == av2 and m == lm2 and "DONE" in t, f"L19 ({V2}): {len(sts[V2]['av-cam.bin'])} + {len(sts[V2]['libmpr.so'])} sites new, every other byte unchanged")
    r, t, a, m = mp("L19", av2, lm2)
    ok(not r.bad and a == av2 and m == lm2 and not r.pwrites and not r.map_writes, "L19 again: no write")
    r, t, a, m = mp("L20", av2, lm2)
    ok(not r.bad and a == av and m == lm0 and "DONE" in t, "L20: both stock again, byte for byte")
    r, t, a, m = mp("N19", av, lm0)
    ok(not r.bad and a == av1 and m == lm1 and "DONE" in t, f"N19 ({V1}, --no-meta): its {len(sts[V1]['av-cam.bin'])} + {len(sts[V1]['libmpr.so'])} sites new, the heights stock")
    r, t, a, m = mp("L20", av1, lm1)
    ok(not r.bad and a == av and m == lm0 and "DONE" in t, "L20 on a camera holding N19's state: both stock again, byte for byte")
    r, t, a, m = mp("L19", av1, lm1)
    ok(not r.bad and a == av2 and m == lm2 and "DONE" in t and len(r.pwrites) == 2 and not r.map_writes, "L19 on a camera holding N19's state: only the two heights written")
    bad_av = bytearray(av)
    bad_av[design(V2)["descriptors"][0]["descriptor"] * 0x90 + 0x392758 + 0x28] ^= 1
    r, t, a, m = mp("L19", bytes(bad_av), lm0)
    ok(not r.bad and a == bytes(bad_av) and m == lm0 and not r.pwrites and not r.map_writes, "L19 with a guard of av-cam.bin wrong (a descriptor's profile key): nothing is written")
    r, t, a, m = mp("L19", av, lm0, pwrite_lost=[sts[V2]["libmpr.so"][0][0]])
    ok(not r.bad and a == av and m == lm0 and "NOT DONE" in t, "L19 with a libmpr.so write lost: everything put back")
    r, t, a, m = mp("L19", av, lm0, stale=[sts[V2]["av-cam.bin"][3][0]])
    ok(not r.bad and a == av and m == lm0 and "NOT DONE" in t, "L19 with the kernel's view not following a write: everything put back")
    for label, path in (("FX3 kit L19 (ogfile2560_hs_s_fx3_v2)", HERE.parent / "helper_fx3/libJit_fx3_L19.so"),
                        ("FX2 kit L19 (ogfile2560_hs_s_fx2_v2)", HERE.parent / "helper_fx2/libJit_fx2_L19.so"),
                        ("A7C II kit level 19 (ogfile2560_hs_s_c2_v1)", HERE.parent / "helper_c2/libJit_c2_level19_ogfile2560_hs_s_c2_v1.so")):
        if path.is_file():
            r, t, a, m = mp("L19", av, lm0, libpath=path)
            ok(not r.bad and a == av and m == lm0 and not r.pwrites and not r.map_writes, f"{label} on an FX30: nothing is written")

    # ---- P29 / P30: the optional playback step
    emu_fx30_playback.cases(ok)
    print("ALL PASS" if not fail else "FAILED: %d" % len(fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
