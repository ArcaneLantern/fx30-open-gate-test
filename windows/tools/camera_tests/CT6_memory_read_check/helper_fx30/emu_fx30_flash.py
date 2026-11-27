"""Run the built FX30 6.01 flash-step libraries (build_fx30_flash.sh: F18 check, F19 apply, F20 put back) in Unicorn against a model of the
camera's main process. Offline; no camera. (Session HS1, 2026-11-27; design fx30flash_v2, modding/FX30_FLASH_ENABLE.md.)

  ..\\..\\..\\work\\venv\\Scripts\\python.exe -I -B emu_fx30_flash.py

The model process (helper/emu_built.py's Run, with pread64 of /proc/self/mem added, which this step uses for every read):
  - appFw.so 6.01 at a load base: its first segment and its data segment as the loader leaves them (relative relocations applied),
    with /proc/self/maps lines as the kernel gives them (r-xp at offset 0, r--p RELRO, rw-p);
  - libObj.so 6.01 the same way, its .bss holding the InfraHotshoe instance pointer (0x2cde00) and reference count;
  - the instance on the heap: vtable word = load base + 0x251c38, count 42 at +0x28, the table pointer at +0x60, and the table as
    KeyConfigAlloc makes it from the stock setting (words 0 and 1 swapped).
A read of an address outside the model's memory answers EIO, as the kernel does for an unmapped address.
Cases: check on stock (READY), apply (DONE: exactly the 14 app sites and 3 shoe words change, nothing else), apply again (NOTHING TO DO,
no write), check when applied (APPLIED), put back (DONE: every byte as stock), put back again, and refusals with nothing written: a guard
wrong (a rule's target, a menu byte beside a flag, libObj code), another table entry different, no instance, a foreign vtable, a count
other than 42, a site holding foreign bytes, appFw.so not mapped, no /proc/self/mem; a lost write (undo: everything back to stock); a
camera with the app sites applied and the shoe table stock (a restarted shoe object): only the three shoe words are written.
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

LIB = ROOT / "work/extracted/fx30_601/0700_part_image/dev/nflasha15/lib"
DESIGN = json.loads((ROOT / "modding/designs/fx30flash_v2.json").read_text(encoding="utf8"))
APP_BASE, OBJ_BASE, HEAP = 0x7F80000000, 0x7FA0000000, 0x5550000000
INST, ARR = HEAP + 0x100, HEAP + 0x1000
in_heap = lambda a: HEAP <= a < HEAP + 0x2000
RESULT = E.RESULT
EIO = 5


def image(path, base):
    """{address: bytes} of a library as loaded at base (relative relocations applied), its maps lines, and its data segment's bss end."""
    import io
    from elftools.elf.elffile import ELFFile
    d = path.read_bytes()
    e = ELFFile(io.BytesIO(d))
    loads = [s for s in e.iter_segments() if s["p_type"] == "PT_LOAD"]
    relro = next(s for s in e.iter_segments() if s["p_type"] == "PT_GNU_RELRO")
    s0, s1 = loads
    seg0 = bytearray(d[:s0["p_filesz"]])
    lo1 = s1["p_vaddr"] & ~0xFFF
    data = bytearray(s1["p_vaddr"] - lo1) + bytearray(d[s1["p_offset"]:s1["p_offset"] + s1["p_filesz"]])
    data += bytes((s1["p_memsz"] - s1["p_filesz"]))
    for sec in e.iter_sections():
        if sec.header.sh_type == "SHT_RELA":
            for r in sec.iter_relocations():
                if r["r_info_type"] == 1027 and lo1 <= r["r_offset"] < lo1 + len(data):
                    struct.pack_into("<Q", data, r["r_offset"] - lo1, base + r["r_addend"])
    name = "/usr/lib/" + path.name
    pg = lambda v: (v + 0xFFF) & ~0xFFF
    relro_end = pg(relro["p_vaddr"] + relro["p_memsz"])
    file_end = pg(s1["p_vaddr"] + s1["p_filesz"])
    maps = [(base, base + pg(s0["p_filesz"]), "r-xp", 0, name),
            (base + lo1, base + relro_end, "r--p", s1["p_offset"] & ~0xFFF, name),
            (base + relro_end, base + file_end, "rw-p", (s1["p_offset"] & ~0xFFF) + relro_end - lo1, name),
            (base + file_end, base + pg(s1["p_vaddr"] + s1["p_memsz"]), "rw-p", 0, "")]
    return {base: bytes(seg0), base + lo1: bytes(data)}, maps


def maps_text(rows):
    out = b"00400000-00409000 r-xp 00000000 fc:8f 81970                              /usr/bin/im.elf\n"
    for lo, hi, perms, off, name in rows:
        out += b"%x-%x %s %08x %s %s\n" % (lo, hi, perms.encode(), off, b"fc:8f 1234" if name else b"00:00 0", name.encode())
    return out


class Run(E.Run):
    """emu_built's process model with pread64 of /proc/self/mem: the step's only way of reading the process's memory."""
    def on_svc(self, uc, intno, _):
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        if x(8) == 67:
            f = self.fds.get(x(0))
            n, off = x(2), x(3)
            if not f or f[1] != "/proc/self/mem":
                self.bad = "pread64 on a descriptor that is not /proc/self/mem"
                ret = -9
            elif not any(a <= off and off + n <= a + size for a, size in self.own_spans):
                ret = -EIO
            else:
                uc.mem_write(x(1), bytes(uc.mem_read(off, n)))
                self.preads.append((off, n))
                ret = n
            uc.reg_write(R.UC_ARM64_REG_X0, ret & 0xFFFFFFFFFFFFFFFF)
            return
        if x(8) == 68 and self.level == 18:
            self.bad = "level 18 wrote memory"
            uc.emu_stop()
            return
        return super().on_svc(uc, intno, _)


E.ALLOWED[18] = E.ALLOWED[2] | {67}                # this step's check: pread64 of /proc/self/mem as well (emu_built's own level 18 is not used here)


def model():
    app, app_maps = image(LIB / "appFw.so", APP_BASE)
    obj, obj_maps = image(LIB / "libObj.so", OBJ_BASE)
    obj_data_at = max(obj)
    od = bytearray(obj[obj_data_at])
    struct.pack_into("<Q", od, OBJ_BASE + 0x2CDE00 - obj_data_at, INST)
    struct.pack_into("<I", od, OBJ_BASE + 0x2CDDF8 - obj_data_at, 1)
    obj[obj_data_at] = bytes(od)
    heap = bytearray(0x2000)
    struct.pack_into("<Q", heap, 0x100, OBJ_BASE + 0x251C38)
    struct.pack_into("<I", heap, 0x100 + 0x28, 42)
    struct.pack_into("<Q", heap, 0x100 + 0x60, ARR)
    heap[0x1000:0x1000 + 1344] = bytes.fromhex(DESIGN["shoe_table_heap_stock"])
    mem = dict(app)
    mem.update(obj)
    mem[HEAP] = bytes(heap)
    rows = app_maps + obj_maps + [(HEAP, HEAP + 0x2000, "rw-p", 0, "[heap]")]
    return mem, rows


def sites():
    """{address: (stock bytes, target bytes)} of every site of the design, as the model holds them."""
    out = {}
    for e in DESIGN["menu_flags"] + DESIGN["rule_slots"]:
        if not e["kind"]:
            continue
        va = APP_BASE + int(e["va"], 16)
        if e["pointer"]:
            enc = lambda p: struct.pack("<Q", APP_BASE + p[1] if p[0] == "rel" else 0)
            out[va] = (enc(e["stock"]), enc(e["new"]))
        else:
            out[va] = (bytes.fromhex(e["stock"]), bytes.fromhex(e["new"]))
    for s in DESIGN["shoe_sites"]:
        out[ARR + int(s["heap_off"], 16)] = (bytes.fromhex(s["stock"]), bytes.fromhex(s["new"]))
    return out


def run(level, mem, rows, files_extra=None, drop=(), pwrite_lost=()):
    files = {"/proc/self/maps": maps_text(rows), "/proc/self/mem": b""}
    for k in drop:
        files.pop(k, None)
    files.update(files_extra or {})
    lib = (HERE / ("libJit_fx30_F%d.so" % level)).read_bytes()
    r = Run(lib, level, files, {"/tmp_wbshd"}, own=mem)
    r.preads = []
    r.pwrite_lost = set(pwrite_lost)
    r.go()
    after = {a: bytes(r.uc.mem_read(a, len(b))) for a, b in mem.items()}
    return r, r.writes.get(RESULT, b"").decode("utf8", "replace"), after


def changed(before, after):
    out = {}
    for a, b in before.items():
        c = after[a]
        if b != c:
            i = 0
            while i < len(b):
                if b[i] != c[i]:
                    j = i
                    while j < len(b) and b[j] != c[j]:
                        j += 1
                    out[a + i] = c[i:j]
                    i = j
                else:
                    i += 1
    return out


def poke(mem, addr, data):
    out = dict(mem)
    for a, b in mem.items():
        if a <= addr < a + len(b):
            bb = bytearray(b)
            bb[addr - a:addr - a + len(data)] = data
            out[a] = bytes(bb)
            return out
    raise ValueError(hex(addr))


def main():
    mem0, rows = model()
    S = sites()
    target = dict(mem0)
    for a, (_, new) in S.items():
        target = poke(target, a, new)
    results, fails = [], 0

    def ok(cond, what, text=""):
        nonlocal fails
        results.append({"case": what, "pass": bool(cond)})
        print(("PASS " if cond else "FAIL ") + what)
        if not cond:
            fails += 1
            print("   " + "\n   ".join(text.splitlines()[-12:]))

    def is_site_change(ch, want_new=True):
        """every changed byte lies in a site and the site now holds its target (or stock) bytes"""
        for a, b in ch.items():
            hit = next((s for s in S if s <= a < s + len(S[s][0])), None)
            if hit is None:
                return False
        return True

    r, t, m = run(18, mem0, rows)
    ok(not r.bad and "verdict: READY" in t and t.startswith("readcheck 1 level 18") and "== done" in t and not changed(mem0, m), "F18 on stock: READY, nothing written", t)
    r, t, m = run(19, mem0, rows)
    ch = changed(mem0, m)
    ok(not r.bad and "DONE: every site holds the target bytes (apply)" in t and m == target and is_site_change(ch) and len(r.pwrites) == len(S),
       "F19 on stock: DONE, exactly the %d sites written (%d app, 3 shoe), nothing else" % (len(S), len(S) - 3), t)
    order = [w[0] for w in r.pwrites]
    shoe_first = all(in_heap(a) for a in order[:3]) and not any(in_heap(a) for a in order[3:])
    rule_last = all(APP_BASE + int(e["va"], 16) in order[-2:] for e in DESIGN["rule_slots"] if e["kind"])
    ok(shoe_first and rule_last, "F19 order: shoe table first, rule slots last")
    r, t, m = run(19, target, rows)
    ok(not r.bad and "NOTHING TO DO" in t and m == target and not r.pwrites, "F19 when applied: NOTHING TO DO, no write", t)
    r, t, m = run(18, target, rows)
    ok(not r.bad and "verdict: APPLIED" in t and m == target, "F18 when applied: APPLIED", t)
    r, t, m = run(20, target, rows)
    ok(not r.bad and "DONE: every site holds the target bytes (put back)" in t and m == mem0 and len(r.pwrites) == len(S), "F20 when applied: DONE, every byte as stock", t)
    order = [w[0] for w in r.pwrites]
    ok(all(APP_BASE + int(e["va"], 16) in order[:2] for e in DESIGN["rule_slots"] if e["kind"]) and all(in_heap(a) for a in order[-3:]) and not any(in_heap(a) for a in order[:-3]),
       "F20 order: rule slots first, shoe table last")
    r, t, m = run(20, mem0, rows)
    ok(not r.bad and "NOTHING TO DO" in t and m == mem0 and not r.pwrites, "F20 on stock: NOTHING TO DO", t)

    def refused(mem, what, **kw):
        r, t, m = run(19, mem, rows, **kw)
        ok(not r.bad and "nothing is written" in t and "DONE" not in t and not r.pwrites and m == mem, "F19 refuses (%s): nothing is written" % what, t)
        r, t, m = run(18, mem, rows, **kw)
        ok(not r.bad and "verdict: NOT READY" in t and m == mem, "F18 says NOT READY (%s)" % what, t)

    refused(poke(mem0, APP_BASE + 0x3DAD048, struct.pack("<I", 0xC37)), "the 'electronic' rule's target changed")
    first_menu = next(e for e in DESIGN["menu_flags"] if e["kind"])
    refused(poke(mem0, APP_BASE + int(first_menu["va"], 16) + 1, b"\x09"), "a byte beside a menu flag")
    refused(poke(mem0, OBJ_BASE + 0xBC34C, b"\x00\x00\x00\x00"), "libObj.so's KeyConfigAlloc")
    refused(poke(mem0, ARR + 32 * 3 + 4, struct.pack("<I", 0x04000005)), "another table entry")
    refused(poke(mem0, OBJ_BASE + 0x2CDE00, bytes(8)), "no InfraHotshoe instance")
    refused(poke(mem0, INST, struct.pack("<Q", OBJ_BASE + 0x251C48)), "a foreign vtable")
    refused(poke(mem0, INST + 0x28, struct.pack("<I", 41)), "41 entries")
    refused(poke(mem0, ARR + 32 * 17 + 4, struct.pack("<I", 0x04000099)), "a shoe site with a foreign key")
    refused(poke(mem0, APP_BASE + 0x48BAAA8, struct.pack("<Q", APP_BASE + 0x1234)), "a rule slot with a foreign pointer")
    refused(poke(mem0, OBJ_BASE + 0x2CDE00, struct.pack("<Q", 0x6660000000)), "an instance pointer into unmapped memory (EIO, no fault)")
    no_app = [row for row in rows if "appFw" not in row[4]]
    r, t, m = run(19, mem0, no_app)
    ok(not r.bad and "appFw.so is not mapped" in t and not r.pwrites and m == mem0, "F19 with appFw.so not in /proc/self/maps: nothing is written", t)
    r, t, m = run(19, mem0, rows, drop=("/proc/self/mem",))
    ok(not r.bad and "/proc/self/mem open failed" in t and not r.pwrites and m == mem0, "F19 without /proc/self/mem: nothing is written", t)
    lost = APP_BASE + int(DESIGN["menu_flags"][4]["va"], 16) if DESIGN["menu_flags"][4]["kind"] else APP_BASE + int(next(e for e in DESIGN["menu_flags"][3:] if e["kind"])["va"], 16)
    r, t, m = run(19, mem0, rows, pwrite_lost=[lost])
    ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and m == mem0, "F19 with a lost write: NOT DONE, everything put back", t)
    mixed = dict(target)
    for s in DESIGN["shoe_sites"]:
        mixed = poke(mixed, ARR + int(s["heap_off"], 16), bytes.fromhex(s["stock"]))
    r, t, m = run(19, mixed, rows)
    ok(not r.bad and "DONE" in t and m == target and len(r.pwrites) == 3 and all(in_heap(w[0]) for w in r.pwrites), "F19 with the app sites applied and the shoe table stock: only the 3 shoe words", t)
    reads_outside = [(a, n) for a, n in r.preads if not any(b <= a and a + n <= b + len(v) for b, v in mem0.items())]
    ok(not reads_outside, "every read lies in the model's memory")
    out = {"about": "helper_fx30/emu_fx30_flash.py: the built F18/F19/F20 libraries in Unicorn against a model of the camera's main process",
           "libraries": {n: __import__("hashlib").sha256((HERE / ("libJit_fx30_%s.so" % n)).read_bytes()).hexdigest() for n in ("F18", "F19", "F20")},
           "cases": results, "failed": fails}
    (ROOT / "evidence/hotshoe/emu_fx30_flash.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("%d cases, %d failed" % (len(results), fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
