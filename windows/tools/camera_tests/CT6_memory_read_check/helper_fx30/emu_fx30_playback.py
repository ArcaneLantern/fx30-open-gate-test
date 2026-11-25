"""Run the FX30 playback-decoder libraries (P29 apply, P30 put back: readcheck.c levels 29 and 30 with avdec8k_fx30_v1) in Unicorn. Offline; no camera.

  C:/Python313/python.exe -B emu_fx30_playback.py        (emu_fx30_write.py runs these cases too)

The harness is helper/emu_built.py's, with a model of what levels 29 and 30 use and nothing more:
  - /dev/mem opened read-write without O_SYNC; the kernel's own view of av-cam.bin (pread) is the memory as the mappings leave it;
  - three mappings only: an anonymous PROT_NONE reservation, the code page MAP_SHARED | MAP_FIXED inside it, and the data page;
  - every store into the two pages and every cache-maintenance instruction is logged in order (the library's dc cvau, ic ivau, dsb ish
    and isb are hooked at their addresses; its one mrs of CTR_EL0 is answered by the model, so that each kind of instruction cache can be tried).
What each case checks: the bytes of av-cam.bin afterwards (all of it), that every store is one aligned 32-bit word at a site, the order of the
stores (apply: code, then the full maintenance sequence, then data; put back: data, then code, then the sequence), that the sequence also
ran once before the first store (the probe), and that the code page was mapped at the kernel address's offset from a 2 MB boundary, so that
each invalidation names the index the kernel's fetches use.
"""
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
import emu_built as E  # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn import arm64_const as R  # noqa: E402

KVA, ALIGN, PAGE = 0xFFFFFFC001000000, 0x200000, 0x1000
PIPT, VIPT, AIVIVT, VPIPT = 0x8444C004, 0x84448004, 0x84444004, 0x84440004      # CTR_EL0 with L1Ip = 3, 2, 1, 0
DATA_VA = E.MAP_BASE + 0x4000000
MASK = (1 << 64) - 1


def design():
    return json.loads((ROOT / "modding/designs/avdec8k_fx30_v1.json").read_text(encoding="utf8"))


def system_instructions(lib):
    """(address in the emulator, kind, register) of every system-class instruction in the library's executable segments."""
    phoff, phentsize, phnum = struct.unpack_from("<Q", lib, 0x20)[0], *struct.unpack_from("<HH", lib, 0x36)
    out = []
    for i in range(phnum):
        ptype, flags, off, vaddr, _pa, filesz, _ms, _al = struct.unpack_from("<IIQQQQQQ", lib, phoff + i * phentsize)
        if ptype != 1 or not flags & 1:
            continue
        for k in range(0, filesz - 3, 4):
            w = struct.unpack_from("<I", lib, off + k)[0]
            if w & 0xFFC00000 != 0xD5000000 or w == 0xD503201F:        # not a system instruction, or a nop (the compiler's padding)
                continue
            a = E.BASE + vaddr + k
            if w & 0xFFFFFFE0 == 0xD50B7B20:
                out.append((a, "dc", w & 31))
            elif w & 0xFFFFFFE0 == 0xD50B7520:
                out.append((a, "ic", w & 31))
            elif w == 0xD5033B9F:
                out.append((a, "dsb", None))
            elif w == 0xD5033FDF:
                out.append((a, "isb", None))
            elif w & 0xFFFFFFE0 == 0xD53B0020:
                out.append((a, "ctr", w & 31))
            else:
                out.append((a, "other %08x" % w, None))
    return out


class PRun(E.Run):
    def __init__(self, lib, level, files, dirs, av, ctr=PIPT, res_at=E.MAP_BASE + 0x5000, stale=(), kview_fail=False,
                 deny_res=False, deny_fixed=False, deny_data=False):
        E.ALLOWED.setdefault(level, {56, 57, 61, 63, 64, 67, 175, 215, 222})
        super().__init__(lib, level, files, dirs)
        self.av, self.av0 = bytearray(av), bytes(av)
        self.ctr, self.res_at, self.stale, self.kview_fail = ctr, res_at, {E.AVCAM_PHYS + o for o in stale}, kview_fail
        self.deny_res, self.deny_fixed, self.deny_data = deny_res, deny_fixed, deny_data
        self.events, self.pieces, self.res, self.code_va, self.devmem_opened = [], {}, None, None, False
        self.sysins = system_instructions(lib)
        for a, kind, rt in self.sysins:
            self.uc.hook_add(UC_HOOK_CODE, self.on_ins, user_data=(kind, rt), begin=a, end=a)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self.on_w, begin=E.MAP_BASE, end=E.MAP_BASE + 0x10000000)

    def piece(self, va):
        for base, (length, phys) in self.pieces.items():
            if base <= va < base + length:
                return base, length, phys
        return None

    def on_ins(self, uc, address, size, ud):
        kind, rt = ud
        if kind in ("dc", "ic"):
            self.events.append((kind, uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % rt))))
        elif kind in ("dsb", "isb"):
            self.events.append((kind,))
        elif kind == "ctr":                                  # the model's CTR_EL0, in place of the emulator's
            self.events.append(("ctr",))
            uc.reg_write(getattr(R, "UC_ARM64_REG_X%d" % rt), self.ctr)
            uc.reg_write(R.UC_ARM64_REG_PC, address + 4)
        else:
            self.bad = "a system instruction the model does not know: " + kind
            uc.emu_stop()

    def on_w(self, uc, access, addr, size, value, _):
        p = self.piece(addr)
        if p:
            self.events.append(("w", p[2] + addr - p[0] - E.AVCAM_PHYS, size, value & MASK, addr))

    def phys_read(self, off, n):
        out = bytearray(self.av[off - E.AVCAM_PHYS:off - E.AVCAM_PHYS + n])
        for base, (length, phys) in self.pieces.items():
            lo, hi = max(phys, off), min(phys + length, off + n)
            if lo < hi:
                out[lo - off:hi - off] = self.uc.mem_read(base + lo - phys, hi - lo)
        return bytes(out)

    def unmap_piece(self, base):
        length, phys = self.pieces.pop(base)
        self.av[phys - E.AVCAM_PHYS:phys - E.AVCAM_PHYS + length] = self.uc.mem_read(base, length)

    def on_svc(self, uc, intno, ud):
        if intno != 2:
            self.bad = "an exception other than svc: %d" % intno
            uc.emu_stop()
            return
        x = lambda n: uc.reg_read(getattr(R, "UC_ARM64_REG_X%d" % n))
        nr = x(8)
        if nr == 56 and self.cstr(x(1)) == "/dev/mem":
            if x(2) & 0xFFFFFFFF != 2:
                self.bad = "/dev/mem opened with flags %#x" % (x(2) & 0xFFFFFFFF)
                ret = -22
            else:
                self.calls.append(("openat", "/dev/mem", "0x2"))
                self.devmem_opened = True
                self.fds[self.next_fd] = ["M", "/dev/mem", 0]
                ret, self.next_fd = self.next_fd, self.next_fd + 1
        elif nr == 222:
            addr, length, prot, flags, fd, off = x(0), x(1), x(2), x(3), x(4), x(5)
            f = self.fds.get(fd)
            devmem = bool(f) and f[0] == "M"
            if addr == 0 and prot == 0 and flags == 0x22 and fd == MASK and off == 0 and length == ALIGN + PAGE and self.res is None:
                if self.deny_res:
                    ret = -12
                else:
                    self.uc.mem_map(self.res_at, length, 0)
                    self.res, ret = (self.res_at, length), self.res_at
            elif prot == 3 and flags == 0x11 and devmem and length == PAGE and self.res and self.res[0] <= addr and addr + PAGE <= sum(self.res) and not addr & 0xFFF:
                if self.deny_fixed:
                    ret = -22
                else:
                    uc.mem_unmap(addr, PAGE)
                    uc.mem_map(addr, PAGE, 3)
                    uc.mem_write(addr, self.phys_read(off, PAGE))
                    self.pieces[addr], self.code_va, ret = (PAGE, off), addr, addr
            elif addr == 0 and prot == 3 and flags == 1 and devmem and length == PAGE and not off & 0xFFF:
                if self.deny_data:
                    ret = -1
                else:
                    uc.mem_map(DATA_VA, PAGE, 3)
                    uc.mem_write(DATA_VA, self.phys_read(off, PAGE))
                    self.pieces[DATA_VA], ret = (PAGE, off), DATA_VA
            else:
                self.bad = "a mapping the model does not allow: addr %#x len %#x prot %d flags %#x fd %d off %#x" % (addr, length, prot, flags, fd, off)
                ret = -22
        elif nr == 215:
            addr, length = x(0), x(1)
            if addr in self.pieces and self.pieces[addr][0] == length and addr == DATA_VA:
                self.unmap_piece(addr)
                uc.mem_unmap(addr, length)
                ret = 0
            elif self.res and (addr, length) == self.res:
                for b in [b for b in self.pieces if addr <= b < addr + length]:
                    self.unmap_piece(b)
                uc.mem_unmap(addr, length)
                self.res, ret = None, 0
            else:
                self.bad = "munmap of something not mapped so: %#x %#x" % (addr, length)
                ret = -22
        elif nr == 67:
            f, n, off = self.fds.get(x(0)), x(2), x(3)
            if not f or f[0] != "M":
                self.bad = "pread64 on a descriptor that is not /dev/mem"
                ret = -9
            elif self.kview_fail:
                ret = -14
            elif not (E.AVCAM_PHYS <= off and off + n <= E.AVCAM_PHYS + len(self.av)):
                self.bad = "pread64 outside av-cam.bin: %#x" % off
                ret = -14
            else:
                data = bytearray(self.phys_read(off, n))
                for k in range(n):
                    if off + k in self.stale:
                        data[k] = self.av0[off + k - E.AVCAM_PHYS]
                uc.mem_write(x(1), bytes(data))
                ret = n
        else:
            return super().on_svc(uc, intno, ud)
        uc.reg_write(R.UC_ARM64_REG_X0, ret & MASK)

    def go(self):
        super().go()
        for b in list(self.pieces):                          # the model's memory as the run left it (nothing should still be mapped)
            self.unmap_piece(b)
        return self


def sync_runs(events, code_va, sites):
    """Indexes in `events` where the full maintenance sequence for every site starts, through the code mapping at code_va."""
    vas = [code_va + (o - (o & ~0xFFF)) for o in sites]
    pat = [("dc", v) for v in vas] + [("dsb",)] + [("ic", v) for v in vas] + [("dsb",), ("isb",)]
    return [i for i in range(len(events) - len(pat) + 1) if events[i:i + len(pat)] == pat]


def cases(ok):
    d = design()
    code = [(int(s["file_off"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"])) for s in d["code_sites"]]
    data = [(int(s["file_off"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"])) for s in d["data_sites"]]
    guards = [(int(g["file_off"], 16), bytes.fromhex(g["bytes"])) for g in d["data_guards"]]
    code_page = int(d["code_page"], 16)
    lib = {L: (HERE / f"libJit_fx30_P{L}.so").read_bytes() for L in (29, 30)}
    av_file = (ROOT / "work/extracted/fx30_601/0700_part_image/dev/nflasha3/av-cam.bin").read_bytes()
    av = bytes([0x5A]) * 0x1000 + av_file[0x1000:]           # as on a camera: the first page is not the file's (no level may depend on it)
    files = E.tree()
    files["/dev/mem"] = b""
    files["/proc/cpuinfo"] = b"processor\t: 0\nBogoMIPS\t: 48.00\nCPU implementer\t: 0x41\nCPU part\t: 0xd04\n\n"   # a model's text (Cortex-A35 = 0xd04)
    dirs = {"/tmp_wbshd", "/sys/module/liro/parameters", "/proc/driver/pcie"}
    code_offs, data_offs = {o for o, _, _ in code}, {o for o, _, _ in data}

    def put(blob, sites, which):
        b = bytearray(blob)
        for o, old, new in sites:
            b[o:o + 4] = new if which else old
        return bytes(b)
    av_code = put(av, code, 1)
    av_all = put(av_code, data, 1)
    av_data_only = put(av, data, 1)

    def run(L, mem, **kw):
        r = PRun(lib[L], L, kw.pop("files", files), dirs, mem, **kw).go()
        return r, r.writes.get(E.RESULT, b"").decode("utf8", "replace")

    def stores(r):
        return [e for e in r.events if e[0] == "w"]

    def shape_ok(r):
        """Every store one aligned 32-bit word at a site; the code page mapped with the kernel's offset from 2 MB; nothing left mapped."""
        return (all(e[2] == 4 and not e[1] & 3 and e[1] in code_offs | data_offs for e in stores(r)) and r.code_va is not None
                and (r.code_va - (KVA + code_page)) % ALIGN == 0 and not r.pieces and r.res is None)

    def order_ok(r, level):
        ev, sw = r.events, [i for i, e in enumerate(r.events) if e[0] == "w"]
        runs = sync_runs(ev, r.code_va, sorted(code_offs))
        first = sw[0] if sw else len(ev)
        if not any(i < first for i in runs):                      # the probe: the sequence once before any store
            return False
        cw = [i for i in sw if ev[i][1] in code_offs]
        dw = [i for i in sw if ev[i][1] in data_offs]
        if cw and not any(i > max(cw) for i in runs):             # the sequence after the last code store
            return False
        if level == 29 and cw and dw:                             # apply: every code store, then the sequence, then data
            return max(cw) < min(dw) and any(max(cw) < i < min(dw) for i in runs)
        if level == 30 and cw and dw:                             # put back: data first
            return max(dw) < min(cw)
        return True

    # the library holds only the instructions the design needs: dc cvau, ic ivau, dsb ish, isb and one mrs of CTR_EL0
    kinds = sorted({k for _, k, _ in system_instructions(lib[29])})
    ok(kinds == ["ctr", "dc", "dsb", "ic", "isb"] and kinds == sorted({k for _, k, _ in system_instructions(lib[30])}),
       "P29 and P30 hold no system instruction but dc cvau, ic ivau, dsb ish, isb and mrs CTR_EL0 (%s)" % ", ".join(kinds))

    r, t = run(29, av)
    ok(not r.bad and bytes(r.av) == av_all and "DONE: every site holds the target bytes (apply)" in t and shape_ok(r) and order_ok(r, 29)
       and len(stores(r)) == 5, "P29 on a stock camera: the 4 code words and the row are new, nothing else in av-cam.bin changed, "
       "code stored first, then the caches, then the row (%d stores, code page at %#x)" % (len(stores(r)), r.code_va or 0))
    for res_at in (E.MAP_BASE, E.MAP_BASE + 0x17000, E.MAP_BASE + 0x18000, E.MAP_BASE + 0x1FF000, E.MAP_BASE + 0x200000 - 0x1000 + 0x123000):
        r, t = run(29, av, res_at=res_at)
        if r.bad or bytes(r.av) != av_all or not shape_ok(r) or not order_ok(r, 29):
            ok(False, "P29 with the reservation at %#x: the code page keeps the kernel's offset from 2 MB" % res_at)
            break
    else:
        ok(True, "P29 with the reservation at five other addresses: the code page always keeps the kernel's offset from 2 MB (%#x)" % ((KVA + code_page) % ALIGN))
    r, t = run(29, av, ctr=VIPT)
    ok(not r.bad and bytes(r.av) == av_all and "instruction cache VIPT" in t and order_ok(r, 29), "P29 with CTR_EL0 saying VIPT: applied the same way")
    for name, ctr in (("AIVIVT", AIVIVT), ("VPIPT/reserved", VPIPT)):
        r, t = run(29, av, ctr=ctr)
        ok(not r.bad and bytes(r.av) == av and not stores(r) and not r.devmem_opened and "neither PIPT nor VIPT" in t and "nothing is written" in t,
           "P29 with CTR_EL0 saying %s: refused before /dev/mem is opened" % name)
    r, t = run(29, av_all)
    ok(not r.bad and bytes(r.av) == av_all and not stores(r) and "NOTHING TO DO" in t and sync_runs(r.events, r.code_va, sorted(code_offs)),
       "P29 again: nothing to do, no store (the cache sequence still runs once)")
    r, t = run(30, av_all)
    ok(not r.bad and bytes(r.av) == av and "DONE: every site holds the target bytes (put back)" in t and shape_ok(r) and order_ok(r, 30) and len(stores(r)) == 5,
       "P30: av-cam.bin is stock again byte for byte, the row put back before the code, the caches after it")
    r, t = run(30, av)
    ok(not r.bad and bytes(r.av) == av and not stores(r) and "NOTHING TO DO" in t, "P30 on a stock camera: nothing to do")
    # half states (a run stopped between its halves): each level finishes in its own order
    r, t = run(29, av_code)
    ok(not r.bad and bytes(r.av) == av_all and [e[1] for e in stores(r)] == sorted(data_offs) and order_ok(r, 29), "P29 with the code new and the row stock: only the row is written")
    r, t = run(29, av_data_only)
    ok(not r.bad and bytes(r.av) == av_all and {e[1] for e in stores(r)} == code_offs and order_ok(r, 29),
       "P29 with the row new and the code stock (the one unsafe half state): the code is written and the caches synced")
    r, t = run(30, av_data_only)
    ok(not r.bad and bytes(r.av) == av and [e[1] for e in stores(r)] == sorted(data_offs), "P30 with only the row new: the row is put back")
    r, t = run(30, av_code)
    ok(not r.bad and bytes(r.av) == av and {e[1] for e in stores(r)} == code_offs and order_ok(r, 30), "P30 with only the code new: the code is put back and the caches synced")

    # refusals: nothing is stored, nothing is synced
    def refused(label, mem, L=29, text="nothing is written", **kw):
        r, t = run(L, mem, **kw)
        ok(not r.bad and bytes(r.av) == mem and not stores(r) and text in t and not r.pieces and r.res is None,
           "%s with %s: nothing is written%s" % ("P%d" % L, label, "" if r.bad is None else " [" + r.bad + "]"))
    for k in (0x0, 0x10, 0x14C, 0x180, 0x200, 0xFFC):              # bytes of the code page that are no site: start, the allocation, between the sites, end (FX30 page 0x217000)
        bad = bytearray(av)
        bad[code_page + k] ^= 1
        refused("the code page's byte %#x not as in the file" % (code_page + k), bytes(bad), text="is not as in the file")
    for o, old, new in code[1:2] + data:
        bad = bytearray(av)
        bad[o:o + 4] = b"\x1f\x20\x03\xd5"
        refused("the site %#x holding other bytes" % o, bytes(bad), text="holds neither set of bytes")
    for g, b in guards:
        bad = bytearray(av)
        bad[g] ^= 1
        refused("the data guard at %#x wrong" % g, bytes(bad), text="is not as in the file")
    refused("the kernel's own view unreadable", av, kview_fail=True, text="cannot be read")
    refused("no address space for the reservation", av, deny_res=True, text="no address space")
    refused("the fixed mapping of the code page refused", av, deny_fixed=True, text="cannot be mapped at the address chosen")
    refused("the data page's mapping refused", av, deny_data=True, text="the data page cannot be mapped")
    for build in ("fx3_702", "a7iv_602"):
        other = (ROOT / f"work/extracted/{build}/0700_part_image/dev/nflasha3/av-cam.bin").read_bytes()
        refused("%s's av-cam.bin in memory" % build, bytes([0x5A]) * 0x1000 + other[0x1000:], text="is not as in the file")
    r, t = run(29, av, files={k: v for k, v in files.items() if k != "/proc/cpuinfo"})
    ok(not r.bad and bytes(r.av) == av_all and "== file /proc/cpuinfo" in t, "P29 without /proc/cpuinfo: reported, and applied")

    # a write not seen in the kernel's view: everything this run wrote is put back, in the put-back order, and the caches synced after the code
    r, t = run(29, av, stale=[data[0][0]])
    ok(not r.bad and bytes(r.av) == av and "NOT DONE: a step failed; every site this run touched was put back" in t and shape_ok(r)
       and sync_runs(r.events, r.code_va, sorted(code_offs))[-1] > max(i for i, e in enumerate(r.events) if e[0] == "w"),
       "P29 with the row's write not seen by the kernel: the row and the four code words put back, the caches synced last")
    r, t = run(29, av, stale=[code[2][0]])                     # the first byte: the one that differs between the two words
    ok(not r.bad and bytes(r.av) == av and "NOT DONE" in t and not any(e[1] in data_offs for e in stores(r)),
       "P29 with the third code word's write not seen: the row is never written, the two before it put back")
    r, t = run(30, av_all, stale=[code[0][0]])
    ok(not r.bad and bytes(r.av) == av_all and "NOT DONE" in t, "P30 with a code word's write not seen: the camera is left as it was (applied), row included")


def main():
    fail = []
    ok = lambda cond, text: (print(("PASS  " if cond else "FAIL  ") + text), fail.append(text) if not cond else None)
    cases(ok)
    print("ALL PASS" if not fail else "FAILED: %d" % len(fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
