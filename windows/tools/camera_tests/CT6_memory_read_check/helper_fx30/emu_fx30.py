"""Run the built FX30 read-only helper in Unicorn against a model camera. Offline; no camera. (FX30 port, 2026-11-26)

  C:/Python313/python.exe -B emu_fx30.py [--show]

helper_fx2/emu_fx2.py with this camera's model (same harness: helper/emu_built.py; the same coprocessor model: only a transfer of one
whole page, direction 0, into the allocated buffer is accepted). Cases, for both libraries (check and dump):
  stock        an FX30 with the 6.01 files and stock memory (NTSC stored records)  -> every check same, verdict READY
  movie        the same after the camera set a 4K movie mode (the sensor register shadow holds matrix column 1) -> READY
  stock-pal    the same with the stored records a PAL camera computes               -> READY (the records are soft sites)
  applied      every design site holding its new bytes, the screen step included    -> TARGET everywhere, verdict READY
  no-screen    the open-gate state without the screen step                          -> open-gate TARGET, screen words STOCK, READY
  no-meta      the encoder side without the MP4 header heights (N19)                -> its sites TARGET, the two heights STOCK, READY
  fx3          the FX3 7.02 files and coprocessor image (the same main-processor code) -> identity DIFFERS, verdict NOT READY
  fx2          the FX2 1.01 files and coprocessor image                             -> identity DIFFERS, verdict NOT READY
  a7iv         the A7 IV 6.02 files and coprocessor image                           -> identity DIFFERS, verdict NOT READY
  no-reserve   a command line without the av-cam reservation                        -> av-cam.bin not read, NOT READY
  applied-b    the same with the sensor design's variant B (ogsq_fx30_v2b)            -> its LC and read-out spans and stored records
               TARGET-B, everything else TARGET, verdict READY
  v1-applied   the sensor design of kit v1 (ogsq_fx30_v1: row 96, sensor registers untouched) still in memory -> its sites are
               neither stock nor v2's, verdict NOT READY (a cold boot is needed before kit v2)
  exists       a result file already present                                        -> nothing done
and the other way round, the published check libraries of the FX3, FX2, ZV-E1 and A7S III kits run on a stock FX30: each must say NOT READY
(an FX30 owner might run one of those kits; their apply scripts start only after a READY check).
"""
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
import emu_built as E  # noqa: E402
from unicorn import arm64_const as R  # noqa: E402

BASE = 0x108000
FACTS = json.loads((HERE / "fx30_expected.json").read_text(encoding="utf8"))
DES = ROOT / "modding/designs"
CP_RANGE = (0xC0000, 0x2700000)                 # the widest of the kits' read ranges: a foreign helper is modelled too
RECS, REC = 0x20D93A4, 0x160


def ex(build, rel):
    return (ROOT / "work/extracted" / build / "0700_part_image/dev" / rel).read_bytes()


def design(name):
    return json.loads((DES / f"{name}.json").read_text(encoding="utf8"))


class Run(E.Run):
    """E.Run with this helper's coprocessor model: cp_image (bytes at 0x108000) and cp_ram {address: bytes} over zeros."""

    def on_import(self, uc, address, size, _):
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        name, ret = self.imports.get(address), 0
        if name == "_Z9dmm_allocjPj":
            self.lib_calls.append(("alloc", x(0) & 0xFFFFFFFF))
            uc.mem_write(x(1), struct.pack("<I", E.BUF_HANDLE))
            ret = self.buf
        elif name == "_Z8dmm_freej":
            self.lib_calls.append(("free", x(0) & 0xFFFFFFFF))
        elif name == "sen_dma_transfer":
            direction, src, dst, n = x(0) & 0xFFFFFFFF, x(1), x(2), x(3) & 0xFFFFFFFF
            self.lib_calls.append(("transfer", direction, src, dst, n))
            if direction != 0 or dst != self.buf or n != 4096 or src & 0xFFF or not CP_RANGE[0] <= src < CP_RANGE[1]:
                self.bad = "a transfer that is not a read of one whole page in range: dir %d src %#x dst %#x size %d" % (direction, src, dst, n)
                uc.emu_stop()
                return
            page = bytearray(4096)
            img = self.cp["image"]
            if BASE <= src < BASE + len(img):
                chunk = img[src - BASE:src - BASE + 4096]
                page[:len(chunk)] = chunk
            for a, blob in self.cp["ram"].items():
                lo, hi = max(a, src), min(a + len(blob), src + 4096)
                if lo < hi:
                    page[lo - src:hi - src] = blob[lo - a:hi - a]
            va = next(v for v, off in self.map_phys.items() if v in self.maps and off <= self.buf < off + self.maps[v]) + self.buf % 4096
            uc.mem_write(va, bytes(page))
        else:
            self.bad = "call of an unexpected import %r" % name
            uc.emu_stop()
            return
        uc.reg_write(R.UC_ARM64_REG_X0, ret)
        uc.reg_write(R.UC_ARM64_REG_PC, uc.reg_read(R.UC_ARM64_REG_X30))

    def go(self):
        self.uc.reg_write(R.UC_ARM64_REG_SP, E.STACK - 0x1000)
        self.uc.reg_write(R.UC_ARM64_REG_X30, E.RET)
        self.uc.emu_start(self.ctor, E.RET, count=3_000_000_000)
        if not self.bad and self.uc.reg_read(R.UC_ARM64_REG_PC) != E.RET:
            self.bad = "the constructor did not return (pc %#x)" % self.uc.reg_read(R.UC_ARM64_REG_PC)
        return self


MATRIX, MROW, COLMAP = 0x1038D1C, 20, 0x1039938


def set_mode(cp, index):
    """What the firmware's 0x8e8218 does when a drive mode is set: the mode's matrix column goes to the register shadow."""
    col = struct.unpack_from("<I", cp, COLMAP - BASE + 4 * index)[0]
    a = MATRIX
    while True:
        ptr = struct.unpack_from("<I", cp, a - BASE)[0]
        if not ptr:
            return
        cp[ptr - BASE] = cp[a - BASE + 4 + col]
        a += MROW


def model(build="fx30_601", applied=False, screen=True, reserve=True, exists=False, enc="ogfile2560_hs_s_fx30_v2", system="ntsc",
          sensor="ogsq_fx30_v2", movie=False):
    cp = bytearray(ex(build, "nflasha8/cpapp-b.bin"))
    av = bytearray(ex(build, "nflasha3/av-cam.bin"))
    libs = {n: ex(build, "nflasha15/lib" + n) for n in ("/libmpr.so", "/libsencore.so", "/libJiritsu.so")}
    lm = bytearray(libs["/libmpr.so"])
    og, oz, fl, sc = design(sensor), design("outsz2560_fx30_v1"), design(enc), design("lcd32dsq_fx30_v1")
    ram = {}
    if build == "fx30_601":                      # the FX30's RAM tables; a foreign body keeps its own image and zeros
        for m, sr in og["stored_records"].items():
            ram[RECS + sr["index"] * REC] = bytes.fromhex(sr[system]["design" if applied else "stock"])
        for g in oz["guards"]:
            ram[int(g["ram_address"], 16)] = bytes.fromhex(g["bytes"])
        for s in oz["sites"]:
            ram[int(s["ram_address"], 16)] = bytes.fromhex(s["new" if applied else "old"])
    if applied:
        for p in og["patches"]:
            a, new = int(p["addr"], 16), bytes.fromhex(p["new"])
            cp[a - BASE:a - BASE + len(new)] = new
        for p in fl["patches"]:
            o, new = int(p["file_off"], 16), bytes.fromhex(p["new"])
            (lm if p["binary"] == "libmpr.so" else av)[o:o + len(new)] = new
        if screen:
            for s in sc["sites"]:
                a = int(s["ram_address"], 16)
                cp[a - BASE:a - BASE + 4] = bytes.fromhex(s["new"])
    if movie:                                    # the camera entered 4K 24p (mode 0x8c0, index 6) after whatever was written
        set_mode(cp, 6)
    lm_at = 0x7F82D15000
    maps = b"".join(b"%x-%x r-xp 00000000 b3:0f 100 /usr/lib%s\n" % (a, a + ((len(libs[n]) + 0xFFF) & ~0xFFF), n.encode())
                    for n, a in (("/libsencore.so", 0x7F80000000), ("/libJiritsu.so", 0x7F81000000), ("/libmpr.so", lm_at)))
    files = E.tree()
    files["/proc/self/maps"] = maps
    files["/proc/meminfo"] = b"MemTotal: 1 kB\n"
    files["/dev/mem"] = b""
    files["/proc/cmdline"] = b"console=ttyS0 " + (b"memrsv=0x01000000@0x401000000:ex " if reserve else b"") + b"warm.mode=2"
    for n, b in libs.items():
        files["/usr/lib" + n] = b
    dirs = {"/tmp_wbshd", "/proc", "/proc/self", "/sys/module/liro/parameters", "/log", "/usr/lib"}
    if exists:
        files[E.RESULT] = b"earlier result\n"
    phys = {FACTS["avcam_phys"]: bytes([0x5A]) * 0x1000 + bytes(av[0x1000:]),      # the first page is not as in the file on a camera (A7S III, 2026-11-21)
            E.BUF_PHYS & ~0xFFF: bytes(0x2000)}
    own = {lm_at: bytes(lm)}
    return files, dirs, phys, {"image": bytes(cp), "ram": ram}, own


def run(lib, **kw):
    files, dirs, phys, cp, own = model(**kw)
    r = Run(lib, 22, files, dirs, phys=phys, cp=cp, own=own)      # level 22: the A7 IV harness's rules for a read-only helper that maps /dev/mem
    r.go()
    return r, r.writes.get(E.RESULT, b"").decode("utf8", "replace")


def main():
    ok = True
    screen_n = sum(1 for s in FACTS["cp_sites"] if s["name"].startswith("screen"))
    hard = [s for s in FACTS["cp_sites"] if not s["name"].startswith(("outsize_guard",))]
    for which in ("check", "dump"):
        lib = (HERE / f"libJit_fx30_{which}.so").read_bytes()
        for case, kw, want in (("stock", {}, ("VERDICT READY", "STOCK")), ("stock-pal", {"system": "pal"}, ("VERDICT READY", "STOCK")),
                               ("movie", {"movie": True}, ("VERDICT READY", "STOCK")),
                               ("applied", {"applied": True, "movie": True}, ("VERDICT READY", "TARGET")),
                               ("applied-b", {"applied": True, "movie": True, "sensor": "ogsq_fx30_v2b"}, ("VERDICT READY", "TARGET-B")),
                               ("v1-applied", {"applied": True, "movie": True, "sensor": "ogsq_fx30_v1"}, ("VERDICT NOT READY", "OTHER")),
                               ("no-screen", {"applied": True, "screen": False}, ("VERDICT READY", "TARGET")),
                               ("no-meta", {"applied": True, "enc": "ogfile2560_hs_s_fx30_v1"}, ("VERDICT READY", "TARGET")),
                               ("fx3", {"build": "fx3_702"}, ("VERDICT NOT READY", "DIFFERS from the 6.01 update")),
                               ("fx2", {"build": "fx2_101"}, ("VERDICT NOT READY", "DIFFERS from the 6.01 update")),
                               ("a7iv", {"build": "a7iv_602"}, ("VERDICT NOT READY", "DIFFERS from the 6.01 update")),
                               ("no-reserve", {"reserve": False}, ("VERDICT NOT READY", "av-cam.bin is not read")), ("exists", {"exists": True}, ())):
            r, text = run(lib, **kw)
            problems = []
            if r.bad:
                problems.append("stopped: " + r.bad)
            if set(r.writes) - {E.RESULT}:
                problems.append("wrote other files: %s" % sorted(set(r.writes) - {E.RESULT}))
            if any(c[0] == "transfer" and c[1] != 0 for c in r.lib_calls):
                problems.append("a transfer towards the coprocessor")
            if case == "exists":
                if r.writes or r.lib_calls:
                    problems.append("did something although a result existed")
            else:
                problems += ["missing %r" % w for w in want if w not in text]
                if "== done" not in text:
                    problems.append("result not complete")
                if case in ("stock", "movie") and ("OTHER" in text.replace("OTHER (not counted", "") or "DIFFERS" in text or "!!" in text.split("== identity")[1]):
                    problems.append("a stock camera is not reported as all stock")
                if case == "stock-pal":
                    recs = [ln for ln in text.split("\n") if ln.startswith("site stored_record_")]
                    if len(recs) != 5 or not all(ln.endswith("OTHER (not counted: filled at run time)") for ln in recs):
                        problems.append("PAL records: %s" % [ln[-45:] for ln in recs])
                    if "DIFFERS" in text or "OTHER  \n" in text:
                        problems.append("a PAL camera's hard sites not all stock")
                if case == "applied" and text.count("TARGET") < len(hard) + FACTS["lm_sites"] + FACTS["av_sites"]:
                    problems.append("not every site reported TARGET: %d" % text.count("TARGET"))
                if case == "no-screen":
                    st = sum(1 for ln in text.split("\n") if ln.startswith("site screen") and ln.endswith("  STOCK"))
                    if st != screen_n or text.count("TARGET") < len(hard) - screen_n + FACTS["lm_sites"] + FACTS["av_sites"]:
                        problems.append("no-screen: %d screen words stock (want %d)" % (st, screen_n))
                if case == "no-meta":                      # N19: its sites TARGET, the two header heights STOCK
                    lm = [ln for ln in text.split("\n") if ln.startswith("lm ")]
                    if sum(ln.endswith("TARGET") for ln in lm) != 4 or sum(ln.endswith("STOCK") for ln in lm) != 2:
                        problems.append("no-meta: libmpr lines %s" % lm)
                SENSOR_SITES = ("site crop", "site window", "site pdaf", "site lc ", "site readout", "site geometry", "site record_", "site sensor_window")
                if case in ("stock", "movie", "applied"):  # the sensor design's nine sites are hard
                    sn = [ln for ln in text.split("\n") if ln.startswith(SENSOR_SITES)]
                    if len(sn) != 9 or not all(ln.endswith("  " + ("TARGET" if case == "applied" else "STOCK")) for ln in sn):
                        problems.append("sensor sites: %s" % sn)
                if case == "applied-b":                    # variant B: the two spans that differ and the five records say TARGET-B, the rest TARGET
                    sn = {ln.split()[1]: ln.rsplit("  ", 1)[1] for ln in text.split("\n") if ln.startswith(SENSOR_SITES + ("site stored_record_",))}
                    want_b = set(FACTS["variant_b_sites"])
                    if len(sn) != 14 or len(want_b) != 7 or any(sn[k] != ("TARGET-B" if k in want_b else "TARGET") for k in sn) or "OTHER" in text.replace("OTHER (not counted", ""):
                        problems.append("variant B sites: %s" % sn)
                if case == "v1-applied":                   # kit v1's state: its matrix bytes are stock, its tables and records are not v2's
                    sn = {ln.split()[1]: ln.rsplit("  ", 1)[1] for ln in text.split("\n") if ln.startswith(SENSOR_SITES)}
                    if sn.get("sensor_window") != "STOCK" or not all(sn.get(k, "").startswith("OTHER") for k in ("crop", "lc", "geometry", "record_left", "record_right")):
                        problems.append("v1 state: %s" % sn)
                if which == "dump" and case == "stock" and text.count("cppage ") != sum(k for _, _, k in FACTS["dump_ranges"]):
                    problems.append("dump pages: %d" % text.count("cppage "))
            n_tr = sum(1 for c in r.lib_calls if c[0] == "transfer")
            print(f"{which:5} {case:10} {'ok' if not problems else 'FAILED'}  result {len(text):7} bytes, {n_tr:3} page reads  {'; '.join(problems)}")
            ok &= not problems
            if "--show" in sys.argv and case == "stock":
                print("\n".join(ln[:150] for ln in text.split("== identity")[1].splitlines()[:80]))
    # ---- the other kits' check libraries on an FX30
    for kit, path, verdict in (("FX3 kit", HERE.parent / "helper_fx3/libJit_fx3_check.so", "DIFFERS from the 7.02 update"),
                               ("FX2 kit", HERE.parent / "helper_fx2/libJit_fx2_check.so", "DIFFERS from the 1.01 update"),
                               ("ZV-E1 kit", HERE.parent / "helper_zv/libJit_zv_check.so", "DIFFERS from the 2.02 update"),
                               ("A7S III kit", HERE.parent / "helper_s3/libJit_s3_check.so", "DIFFERS from the 5.01 update")):
        if not path.is_file():
            print(f"foreign {kit}: library not here, skipped")
            continue
        r, text = run(path.read_bytes())
        good = not r.bad and "VERDICT NOT READY" in text and verdict in text and not (set(r.writes) - {E.RESULT})
        print(f"foreign {kit:12} on a stock FX30: {'ok, NOT READY' if good else 'FAILED'}  {r.bad or ''}")
        ok &= good
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
