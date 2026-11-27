"""The memory-card speed check of movie recording (the "V90 for XAVC S-I" rule), decoded for ANY indexed build (session MR1, 2026-11-27).

Where it is (FX30 6.01 and A7 IV 6.02 read by hand first, then generalised): libmpr.so, class RateCheck.
  getMediaTransferRateCheckType_Normal / _SnQ          dispatch on the movie record format (movieRecParam field, F128) to one leaf per family
  getMediaTransferRateCheckType_<mode>_<codec>_<size>  look the setting up in a table of rows {keys..., check type}; no row -> type 0
  GetMediaTransferRateInh(drive, movieRecParam, bool&, InhBit&)
                                                       reads the card's drive info (Fsys_GetDriveInfo, libInfraFsys.so: transferRate in
                                                       Mbps, filesystemType), switches on the check type 1..6, compares the card's rate
                                                       with a fixed threshold and sets one inhibit bit when the card is too slow; type 0
                                                       (setting not in the table) sets 0x400 and returns 3
  callers: mpr::GetMovieRecStatus and the movie-status update; the bits go into the slot's movie-record status, which appFw.so turns into
  movie_recording_inhibit_cause_by_system_and_media_rate_slotN (NEED_OVER_80/240/480/720/1600_MBPS_MEDIA) and, through four exclusion
  rules, "movie not recordable" on that slot (caution STRID_CAU_MOVIE_MEDIA_RESTRICTION_V90_FILE_FORMAT and its siblings).

What this script does, per build (everything from the build's own libmpr.so; nothing is hard-coded but symbol names):
  1. finds the RateCheck functions by their dynamic symbols, the PLT stub of every import, and the RELATIVE relocations;
  2. decodes every leaf's table statically (capstone): table address through its GOT slot, row count, row size, which movieRecParam field
     each key is compared with, the type byte; the frame-rate mapping functions are run in Unicorn for inputs 0..63;
  3. runs GetMediaTransferRateInh itself in Unicorn (imports stubbed: Fsys_GetDriveInfo fills the drive info, the two dispatchers return
     the check type under test, memcpy/memset work, every other import returns 0) and measures, for each check type 0..7 and filesystem
     type 3 and 4, the lowest card rate that passes and the inhibit bit set below it (binary search, then checked at sample rates);
  4. finds the "remove" patch: every `str w0, [<param 4>]` right after `mov w0, #<speed bit>` (0x800..0x8000), NOP; runs the patched
     function the same way and checks that types 1..6 never inhibit, while the return value, the bool output and type 0/7 behave as stock;
  5. lists the BL sites that reach the compare helper and the PLT stub of GetMediaTransferRateInh (who calls the check).

  python -I -B build/media_rate_check.py <build> [<build> ...]       writes evidence/media_rate/media_rate_<build>.json, prints a summary
  python -I -B build/media_rate_check.py --all                       every build in curated/builds.jsonl that has libmpr.so
  python -I -B build/media_rate_check.py <build> --design NAME       also writes modding/designs/NAME.json (the "remove" patch: sites,
                                                                     stock and new bytes, the guard range = the helper and the check)
Read-only on firmware.
"""
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import locate_file  # noqa: E402

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs  # noqa: E402
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG  # noqa: E402
from elftools.elf.elffile import ELFFile  # noqa: E402
from elftools.elf.relocation import RelocationSection  # noqa: E402
from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_MODE_ARM, Uc, UcError  # noqa: E402
from unicorn.arm64_const import (UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_X0, UC_ARM64_REG_X1,  # noqa: E402
                                 UC_ARM64_REG_X2, UC_ARM64_REG_X3)

ROOT = common.ROOT
OUT_DIR = ROOT / "evidence" / "media_rate"
DESIGNS = ROOT / "modding" / "designs"
NOP = bytes.fromhex("1f2003d5")
SPEED_BITS = {0x800: "NEED_OVER_80_MBPS (Class 10 / U1)", 0x1000: "NEED_OVER_240_MBPS (U3 / V30)", 0x2000: "NEED_OVER_480_MBPS (V60)",
              0x4000: "NEED_OVER_720_MBPS (V90)", 0x8000: "NEED_OVER_1600_MBPS (CFexpress VPG200 / VPG400)"}
INH_TEXT = {0: "none", 0x400: "UNAVAILABLE_SETTING (setting not in the table)", **SPEED_BITS}
CARD_RATES = {"Class 10 / UHS U1 (SD)": 80, "U3 / V30, or V60/V90 on a UHS-I bus (SD); plain NVMe or CFexpress without VPG": 240,
              "V60 on UHS-II (SD)": 480, "V90 on UHS-II (SD)": 720}
SYM_PREFIX = "_ZN9RateCheck"
MAGIC_RET = 0x7F000000
STACK, STACK_SZ = 0x70000000, 0x100000
SCRATCH, SCRATCH_SZ = 0x71000000, 0x10000
PROBE_RATES = [0, 1, 79, 80, 81, 119, 120, 121, 239, 240, 241, 399, 400, 401, 479, 480, 481, 599, 600, 601, 719, 720, 721, 1349, 1350,
               1351, 1599, 1600, 2699, 2700, 2701, 3200, 6400, 12800, 65535]


def demangle_rc(name):
    """_ZN9RateCheck<len><name>... -> the method name."""
    s = name[len(SYM_PREFIX):]
    n = ""
    while s and s[0].isdigit():
        n += s[0]
        s = s[1:]
    return s[:int(n)] if n else name


class Lib:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        self.elf = ELFFile(io.BytesIO(self.data))
        self.loads = [(s["p_vaddr"], s["p_memsz"], s["p_offset"], s["p_filesz"], s["p_flags"])
                      for s in self.elf.iter_segments() if s["p_type"] == "PT_LOAD"]
        self.syms = {}
        dyn = self.elf.get_section_by_name(".dynsym")
        for s in dyn.iter_symbols():
            if s["st_value"] and s.name:
                self.syms[s.name] = (s["st_value"], s["st_size"])
        self.relative = {}
        self.jump_slot = {}
        for sec in self.elf.iter_sections():
            if not isinstance(sec, RelocationSection):
                continue
            symtab = self.elf.get_section(sec["sh_link"])
            for r in sec.iter_relocations():
                t = r["r_info_type"]
                if t == 1027:                                                  # R_AARCH64_RELATIVE
                    self.relative[r["r_offset"]] = r["r_addend"]
                elif t in (1026, 1025):                                        # JUMP_SLOT, GLOB_DAT
                    self.jump_slot[r["r_offset"]] = symtab.get_symbol(r["r_info_sym"]).name
        self.cs = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        self.cs.detail = True
        self.plt = self._plt_stubs()

    def off(self, va):
        for v, msz, o, fsz, _ in self.loads:
            if v <= va < v + fsz:
                return o + va - v
        return -1

    def read(self, va, n):
        o = self.off(va)
        return self.data[o:o + n] if o >= 0 else b""

    def u64(self, va):
        if va in self.relative:
            return self.relative[va]
        b = self.read(va, 8)
        return struct.unpack("<Q", b)[0] if len(b) == 8 else 0

    def disasm(self, va, size):
        return list(self.cs.disasm(self.read(va, size), va))

    def _plt_stubs(self):
        sec = self.elf.get_section_by_name(".plt")
        out = {}
        if not sec:
            return out
        lo, size = sec["sh_addr"], sec["sh_size"]
        ins = self.disasm(lo, size)
        for i in range(len(ins) - 1):
            a, b = ins[i], ins[i + 1]
            if a.mnemonic == "adrp" and b.mnemonic == "ldr" and a.operands[0].reg == b.operands[1].mem.base:
                slot = a.operands[1].imm + b.operands[1].mem.disp
                if slot in self.jump_slot:
                    out[a.address] = self.jump_slot[slot]
        return out

    def plt_of(self, name):
        return next((a for a, n in self.plt.items() if n == name), None)

    def bl_sites(self, target):
        """Every BL in the executable segment whose target is `target`."""
        out = []
        for v, msz, o, fsz, fl in self.loads:
            if not fl & 1:
                continue
            seg = self.data[o:o + fsz]
            for k in range(0, len(seg) - 3, 4):
                w = struct.unpack_from("<I", seg, k)[0]
                if w & 0xFC000000 == 0x94000000:
                    imm = w & 0x3FFFFFF
                    if imm & 0x2000000:
                        imm -= 0x4000000
                    if v + k + imm * 4 == target:
                        out.append(v + k)
        return out

    def containing_symbol(self, va):
        best = None
        for n, (a, s) in self.syms.items():
            if a <= va < a + max(s, 1) and (best is None or a > best[1]):
                best = (n, a)
        return best


# ---------------------------------------------------------------------------------------------------------------- emulation
class Emu:
    def __init__(self, lib, patches=()):
        self.lib = lib
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = set()
        for v, msz, o, fsz, _ in lib.loads:
            pages.update(range(v >> 12, (v + msz + 0xFFF) >> 12))
        run = None
        for p in sorted(pages) + [None]:                                   # map contiguous runs of pages once
            if run and p == run[1]:
                run[1] += 1
                continue
            if run:
                uc.mem_map(run[0] << 12, (run[1] - run[0]) << 12)
            run = [p, p + 1] if p is not None else None
        for v, msz, o, fsz, _ in lib.loads:
            uc.mem_write(v, lib.data[o:o + fsz])
        for at, add in lib.relative.items():
            uc.mem_write(at, struct.pack("<Q", add))
        for at, b in patches:
            uc.mem_write(at, b)
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(SCRATCH, SCRATCH_SZ)
        uc.mem_map(MAGIC_RET & ~0xFFF, 0x1000)
        self.uc = uc
        self.handlers = {}                       # import name -> handler(uc, [x0..x3]) returning x0
        self.addr_handlers = {}                  # local function address -> handler, for direct calls
        self.reads = []
        self.drive_buf = None
        plt_lo = min(lib.plt) if lib.plt else 0
        plt_hi = max(lib.plt) + 16 if lib.plt else 0
        if lib.plt:
            uc.hook_add(UC_HOOK_CODE, self._on_plt, begin=plt_lo, end=plt_hi)
        uc.hook_add(UC_HOOK_MEM_READ, self._on_read, begin=STACK, end=SCRATCH + SCRATCH_SZ)

    def hook_local(self, addr, handler):
        self.addr_handlers[addr] = handler
        self.uc.hook_add(UC_HOOK_CODE, self._on_local, begin=addr, end=addr)

    def _on_local(self, uc, addr, size, _):
        h = self.addr_handlers.get(addr)
        if h is None:
            return
        x = [uc.reg_read(UC_ARM64_REG_X0 + i) for i in range(4)]
        uc.reg_write(UC_ARM64_REG_X0, h(uc, x) & 0xFFFFFFFFFFFFFFFF)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def _on_plt(self, uc, addr, size, _):
        name = self.lib.plt.get(addr)
        if name is None:
            return
        x = [uc.reg_read(UC_ARM64_REG_X0 + i) for i in range(4)]
        h = self.handlers.get(name)
        if h:
            r = h(uc, x)
        elif name in ("memcpy", "memmove"):
            uc.mem_write(x[0], bytes(uc.mem_read(x[1], x[2]))) if x[2] else None
            r = x[0]
        elif name == "memset":
            uc.mem_write(x[0], bytes([x[1] & 0xFF]) * x[2]) if x[2] else None
            r = x[0]
        else:
            r = 0
        uc.reg_write(UC_ARM64_REG_X0, r & 0xFFFFFFFFFFFFFFFF)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def _on_read(self, uc, access, addr, size, value, _):
        if self.drive_buf is not None and self.drive_buf <= addr < self.drive_buf + 0x100:
            self.reads.append((addr - self.drive_buf, size))

    def call(self, fn, args, limit=200000):
        uc = self.uc
        for i, a in enumerate(args):
            uc.reg_write(UC_ARM64_REG_X0 + i, a)
        uc.reg_write(UC_ARM64_REG_SP, STACK + STACK_SZ - 0x1000)
        uc.reg_write(UC_ARM64_REG_LR, MAGIC_RET)
        uc.emu_start(fn, MAGIC_RET, count=limit)
        return uc.reg_read(UC_ARM64_REG_X0)


def run_inh(lib, fn, ctype, rate, fstype, offsets, patches=()):
    """GetMediaTransferRateInh(drive 'C', zeroed movieRecParam, &bool, &inh) with the check type forced; returns (ret, bool, inh, emu)."""
    e = Emu(lib, patches)
    rate_off, fs_off = offsets

    def drive(uc, x):
        e.drive_buf = x[1]
        buf = bytearray(0x100)
        if rate_off is not None:
            struct.pack_into("<I", buf, rate_off, rate)
        if fs_off is not None:
            struct.pack_into("<H", buf, fs_off, fstype)
        uc.mem_write(x[1], bytes(buf))
        return 0
    e.handlers["Fsys_GetDriveInfo"] = drive
    for n in lib.plt.values():
        if n.startswith(SYM_PREFIX) and "CheckType" in n:
            e.handlers[n] = lambda uc, x: ctype
    for n, (a, s) in lib.syms.items():                                     # direct calls, if the build makes them
        if n.startswith(SYM_PREFIX) and "CheckType" in n:
            e.hook_local(a, lambda uc, x: ctype)
    param, boolp, inhp = SCRATCH, SCRATCH + 0x800, SCRATCH + 0x810
    e.uc.mem_write(SCRATCH, bytes(0x900))
    e.uc.mem_write(boolp, b"\xaa")
    e.uc.mem_write(inhp, b"\x55\x55\x55\x55")
    ret = e.call(fn, [ord("C"), param, boolp, inhp])
    b = e.uc.mem_read(boolp, 1)[0]
    inh = struct.unpack("<I", bytes(e.uc.mem_read(inhp, 4)))[0]
    return ret & 0xFFFFFFFF, b, inh, e


def learn_offsets(lib, fn):
    """Which drive-info offsets the check reads: run type 4 with a zero buffer and log the reads (4-byte read = rate, 2-byte = fs)."""
    _, _, _, e = run_inh(lib, fn, 4, 0, 0, (None, None))
    rate = sorted({o for o, s in e.reads if s == 4})
    fs = sorted({o for o, s in e.reads if s == 2})
    return (rate[0] if rate else None, fs[0] if fs else None), e.reads


def measure(lib, fn, offsets, patches=()):
    rows = []
    for ctype in range(8):
        for fstype in (3, 4):
            samples = [(r,) + run_inh(lib, fn, ctype, r, fstype, offsets, patches)[:3] for r in PROBE_RATES]
            passing = [r for r, ret, b, inh in samples if inh == 0]
            failing = [(r, inh) for r, ret, b, inh in samples if inh != 0]
            # the exact threshold: the lowest passing rate, by binary search between the last failing and first passing sample
            exact = None
            if passing and failing and min(passing) > max(r for r, _ in failing):
                lo, hi = max(r for r, _ in failing), min(passing)
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if run_inh(lib, fn, ctype, mid, fstype, offsets, patches)[2] == 0:          # (ret, bool, inh, emu)
                        hi = mid
                    else:
                        lo = mid
                exact = hi
            rows.append({"type": ctype, "filesystem_type": fstype,
                         "lowest_passing_rate_mbps": exact if exact is not None else (0 if not failing else None),
                         "passes_at_all_rates": not failing, "fails_at_all_rates": not passing,
                         "inhibit_when_too_slow": sorted({hex(i) for _, i in failing}),
                         "return_values": sorted({ret for _, ret, _, _ in samples}),
                         "bool_out": sorted({b for _, _, b, _ in samples}),
                         "samples": [{"rate": r, "ret": ret, "bool": b, "inh": hex(inh)} for r, ret, b, inh in samples]})
    return rows


# ---------------------------------------------------------------------------------------------------------------- static decoding
def reg_name(cs, r):
    return cs.reg_name(r)


def decode_leaf(lib, name, va, size):
    """A getMediaTransferRateCheckType_<...> leaf: its table rows and which movieRecParam fields its keys are compared with."""
    ins = lib.disasm(va, size)
    cs = lib.cs
    base_regs = {"x0"}
    src = {}                                    # register -> description of what it holds
    calls = []
    table, count, stride, type_off = None, None, None, None
    cmps = []                                   # (row offset, size, source description)
    pending_got = {}
    row_reg = None
    last_row_load = {}
    for i in ins:
        m, ops = i.mnemonic, i.operands
        if m == "mov" and len(ops) == 2 and ops[1].type == ARM64_OP_REG:
            d, s = reg_name(cs, ops[0].reg), reg_name(cs, ops[1].reg)
            if s in base_regs:
                base_regs.add(d)
            if s in src:
                src[d] = src[s]
            pending_got.pop(d, None)
        elif m in ("ldr", "ldrb", "ldrh", "ldrsw") and ops[1].type == ARM64_OP_MEM:
            d = reg_name(cs, ops[0].reg)
            b = reg_name(cs, ops[1].mem.base)
            disp = ops[1].mem.disp
            if b in base_regs and d[0] == "w":
                src[d] = f"param+{disp:#x}" + (" (byte)" if m == "ldrb" else "")
                src["x" + d[1:]] = src[d]
            elif m == "ldr" and d[0] == "x" and b in pending_got:              # ldr xD, [xP, #off] after adrp xP: a GOT slot
                tab = lib.u64(pending_got[b] + disp)
                if tab:
                    table = table or tab
                    src[d] = "table"
                    if row_reg is None:
                        row_reg = d
            elif row_reg and b == row_reg and d[0] == "w":
                last_row_load[d] = (disp, {"ldr": 4, "ldrb": 1, "ldrh": 2, "ldrsw": 4}[m])
            elif d[0] == "w" and m == "ldrb" and src.get(b) == "row":
                type_off = disp                 # ldrb w0, [x1, #T] on the selected row (after madd)
            if d[0] == "x" and src.get(d) != "table":
                pending_got.pop(d, None)
            if d[0] == "x" and b in pending_got and src.get(d) == "table":
                pending_got.pop(d, None)
        elif m == "madd":
            d = reg_name(cs, ops[0].reg)
            src[d] = "row"
            pending_got.pop(d, None)
        elif m == "adrp":
            pending_got[reg_name(cs, ops[0].reg)] = ops[1].imm
        elif m == "bl":
            tgt = ops[0].imm
            calls.append(tgt)
            arg = src.get("w0", "?")
            src["w0"] = f"map_{tgt:#x}({arg})"
            src["x0"] = src["w0"]
            base_regs.discard("x0")
        elif m == "cmp" and len(ops) == 2:
            a = reg_name(cs, ops[0].reg)
            if ops[1].type == ARM64_OP_IMM:
                if a.startswith("x") and count is None:
                    count = ops[1].imm
            else:
                b = reg_name(cs, ops[1].reg)
                for r1, r2 in ((a, b), (b, a)):
                    if r2 in last_row_load and r1 in src:
                        cmps.append((last_row_load[r2][0], last_row_load[r2][1], src[r1]))
        elif m == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
            d, s = reg_name(cs, ops[0].reg), reg_name(cs, ops[1].reg)
            if d == s and d == row_reg and ops[2].imm > 1:
                stride = ops[2].imm
        elif m == "add" and len(ops) == 3 and ops[2].type == ARM64_OP_REG:     # add x2, x2, w3, sxtw #4: the selected row
            d, s = reg_name(cs, ops[0].reg), reg_name(cs, ops[1].reg)
            if src.get(s) == "table":
                src[d] = "row"
                pending_got.pop(d, None)
    seen_off = set()
    cmps = [c for c in cmps if not (c[0] in seen_off or seen_off.add(c[0]))]
    rows = []
    if table and count and stride:
        raw = lib.read(table, count * stride)
        for r in range(count):
            row = raw[r * stride:(r + 1) * stride]
            keys = []
            for o, sz, what in cmps:
                v = int.from_bytes(row[o:o + sz], "little")
                keys.append({"row_offset": o, "field": what, "value": v})
            rows.append({"keys": keys, "type": row[type_off] if type_off is not None else None, "raw": row.hex()})
    return {"name": name, "va": hex(va), "size": size, "table": hex(table) if table else None, "rows_n": count, "row_size": stride,
            "type_offset": type_off, "compares": [{"row_offset": o, "size": s, "field": w} for o, s, w in cmps],
            "calls": [hex(c) for c in calls], "rows": rows}


def run_map(lib, fn, n=64):
    out = {}
    for v in range(n):
        try:
            e = Emu(lib)
            out[v] = e.call(fn, [v], limit=2000) & 0xFFFFFFFF
        except UcError:
            out[v] = None
    return out


def decode_dispatch(lib, va, size):
    """getMediaTransferRateCheckType_Normal / _SnQ: which record-format values go to which leaf."""
    ins = lib.disasm(va, size)
    field = None
    for i in ins:
        if i.mnemonic == "ldr" and i.operands[1].type == ARM64_OP_MEM and lib.cs.reg_name(i.operands[1].mem.base) == "x0":
            field = i.operands[1].mem.disp
            break
    out = {}
    for fmt in range(32):
        e = Emu(lib)
        seen = []
        leafs = {n: a for n, (a, s) in lib.syms.items() if n.startswith(SYM_PREFIX) and "CheckType" in n}
        for n in lib.plt.values():
            if n in leafs:
                e.handlers[n] = (lambda name: (lambda uc, x: seen.append(name) or 0x99))(n)
        for n, a in leafs.items():
            if a != va:
                e.hook_local(a, (lambda name: (lambda uc, x: seen.append(name) or 0x99))(n))
        par = SCRATCH
        e.uc.mem_write(par, bytes(0x900))
        if field is not None:
            e.uc.mem_write(par + field, struct.pack("<I", fmt))
        try:
            r = e.call(va, [par], limit=20000)
        except UcError as ex:
            out[fmt] = f"error {ex}"
            continue
        out[fmt] = demangle_rc(seen[0]) if seen else ("none" if (r & 0xFF) == 0 else f"ret {r:#x}")
    return {"format_field": hex(field) if field is not None else None, "by_format": out}


def find_patch_sites(lib, va, size):
    ins = lib.disasm(va, size)
    cs = lib.cs
    p4 = None
    for i in ins[:64]:                                                     # the prologue copies x3 (InhBit&) to a callee-saved register
        if i.mnemonic == "mov" and len(i.operands) == 2 and i.operands[1].type == ARM64_OP_REG and cs.reg_name(i.operands[1].reg) == "x3":
            p4 = cs.reg_name(i.operands[0].reg)
            break
    sites = []
    for a, b in zip(ins, ins[1:]):
        if (a.mnemonic == "mov" and a.operands[0].type == ARM64_OP_REG and cs.reg_name(a.operands[0].reg) == "w0"
                and a.operands[1].type == ARM64_OP_IMM and a.operands[1].imm in SPEED_BITS
                and b.mnemonic == "str" and cs.reg_name(b.operands[0].reg) == "w0" and b.operands[1].type == ARM64_OP_MEM
                and cs.reg_name(b.operands[1].mem.base) == p4 and b.operands[1].mem.disp == 0):
            sites.append({"va": hex(b.address), "file_off": hex(lib.off(b.address)), "stock": bytes(b.bytes).hex(), "new": NOP.hex(),
                          "insn": f"{b.mnemonic} {b.op_str}", "after": f"{a.mnemonic} {a.op_str}"})
    return p4, sites


def summarise_types(meas):
    out = {}
    for r in meas:
        t = out.setdefault(r["type"], {})
        key = f"fs{r['filesystem_type']}"
        if r["passes_at_all_rates"]:
            t[key] = "passes at any rate"
        elif r["fails_at_all_rates"]:
            t[key] = "fails at any rate: " + ",".join(r["inhibit_when_too_slow"])
        else:
            t[key] = f"passes from {r['lowest_passing_rate_mbps']} Mbps, else " + ",".join(r["inhibit_when_too_slow"])
    return out


def analyse(build):
    try:
        path = locate_file.locate(build, "libmpr.so")
    except SystemExit:
        return None
    lib = Lib(path)
    rc = {demangle_rc(n): (a, s, n) for n, (a, s) in lib.syms.items() if n.startswith(SYM_PREFIX)}
    if "GetMediaTransferRateInh" not in rc:
        return {"build": build, "libmpr_sha256": lib.sha256, "rate_check": None}
    fa, fs_, fmang = rc["GetMediaTransferRateInh"]
    # the compare helper: the local function the check BLs to most often
    ins = lib.disasm(fa, fs_)
    bls = [i.operands[0].imm for i in ins if i.mnemonic == "bl"]
    helper = max(set(bls), key=bls.count) if bls else None
    offsets, reads = learn_offsets(lib, fa)
    stock = measure(lib, fa, offsets)
    p4, sites = find_patch_sites(lib, fa, fs_)
    patched = measure(lib, fa, offsets, [(int(s["va"], 16), NOP) for s in sites]) if sites else None
    verify = None
    if patched:
        problems = []
        for s, p in zip(stock, patched):
            t = s["type"]
            if 1 <= t <= 6:
                if not p["passes_at_all_rates"]:
                    problems.append(f"type {t} fs {s['filesystem_type']}: still inhibits")
            elif [x["inh"] for x in s["samples"]] != [x["inh"] for x in p["samples"]]:
                problems.append(f"type {t} fs {s['filesystem_type']}: inhibit differs from stock")
            if [(x["ret"], x["bool"]) for x in s["samples"]] != [(x["ret"], x["bool"]) for x in p["samples"]]:
                problems.append(f"type {t} fs {s['filesystem_type']}: return value or bool output differs from stock")
        verify = {"ok": not problems, "problems": problems}
    leaves, maps = {}, {}
    for short, (a, s, n) in sorted(rc.items(), key=lambda kv: kv[1][0]):
        if short.startswith("getMediaTransferRateCheckType_") and short not in ("getMediaTransferRateCheckType_Normal", "getMediaTransferRateCheckType_SnQ"):
            leaves[short] = decode_leaf(lib, short, a, s)
            for c in leaves[short]["calls"]:
                if c not in maps:
                    maps[c] = run_map(lib, int(c, 16))
    dispatch = {k: decode_dispatch(lib, rc[k][0], rc[k][1]) for k in ("getMediaTransferRateCheckType_Normal", "getMediaTransferRateCheckType_SnQ") if k in rc}
    plt = lib.plt_of(fmang)
    callers = []
    for site in (lib.bl_sites(plt) if plt else []) + lib.bl_sites(fa):
        cs = lib.containing_symbol(site)
        callers.append({"site": hex(site), "in": cs[0] if cs else None})
    helper_callers = [hex(x) for x in lib.bl_sites(helper)] if helper else []
    lo = min(fa, helper) if helper else fa
    hi = fa + fs_
    return {"build": build, "libmpr": str(Path(path).relative_to(ROOT)), "libmpr_sha256": lib.sha256,
            "rate_check": {"GetMediaTransferRateInh": {"va": hex(fa), "size": fs_, "file_off": hex(lib.off(fa)), "plt_stub": hex(plt) if plt else None},
                           "compare_helper": {"va": hex(helper) if helper else None, "bl_sites": helper_callers},
                           "drive_info_offsets": {"transferRate": offsets[0], "filesystemType": offsets[1],
                                                  "reads_seen": sorted({f"{o:#x}/{s}" for o, s in reads})},
                           "param4_register": p4, "callers": callers,
                           "functions": {k: {"va": hex(v[0]), "size": v[1]} for k, v in rc.items()}},
            "check_types": summarise_types(stock), "measure_stock": stock,
            "remove_patch": {"sites": sites, "guard_range": [hex(lo), hex(hi)], "verify": verify,
                             "check_types_after": summarise_types(patched) if patched else None},
            "dispatch": dispatch, "leaves": leaves, "frame_rate_maps": {k: {str(i): v for i, v in m.items()} for k, m in maps.items()}}


def type_census(res):
    out = {}
    for name, leaf in (res.get("leaves") or {}).items():
        c = {}
        for r in leaf["rows"]:
            c[r["type"]] = c.get(r["type"], 0) + 1
        out[name] = dict(sorted(c.items()))
    return out


def write_design(res, name):
    rc = res["rate_check"]
    lib = Lib(ROOT / res["libmpr"])
    lo, hi = (int(x, 16) for x in res["remove_patch"]["guard_range"])
    sites = res["remove_patch"]["sites"]
    assert sites and res["remove_patch"]["verify"]["ok"], "the patch did not verify"
    d = {"design": name, "build": res["build"],
         "title": "Card-speed check of movie recording removed: RateCheck::GetMediaTransferRateInh (libmpr.so) never sets a "
                  "'card too slow' bit (Class 10, V30, V60, V90, CFexpress VPG); a setting missing from Sony's tables is still refused",
         "generated_by": "build/media_rate_check.py --design",
         "artifact_sha256": {"libmpr.so": res["libmpr_sha256"]},
         "function": rc["GetMediaTransferRateInh"], "compare_helper": rc["compare_helper"]["va"],
         "sites": [{"va": s["va"], "file_off": s["file_off"], "len": 4, "stock": s["stock"], "new": s["new"],
                    "label": f"{s['insn']} after {s['after']} -> nop"} for s in sites],
         "guard": {"va": hex(lo), "file_off": hex(lib.off(lo)), "len": hi - lo, "stock": lib.read(lo, hi - lo).hex(),
                   "about": "the compare helper and the whole check, as in the file; the sites inside it are compared separately"},
         "elf_header": {"va": "0x0", "len": 64, "stock": lib.read(0, 64).hex()},
         "check_types_stock": res["check_types"], "check_types_after": res["remove_patch"]["check_types_after"],
         "verify": res["remove_patch"]["verify"],
         "while_applied": ["any card may be chosen for any movie setting Sony's tables list; a card that cannot keep up stops the recording "
                           "with the camera's own write error instead of refusing to start",
                           "takes effect at the next movie-status update (insert the card again, or change a movie setting)",
                           "a cold boot (battery out) undoes it"]}
    out = DESIGNS / f"{name}.json"
    out.write_text(json.dumps(d, indent=1) + "\n", encoding="utf8")
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    design = None
    if "--design" in args:
        k = args.index("--design")
        design = args[k + 1]
        del args[k:k + 2]
    if args == ["--all"]:
        args = [json.loads(l)["build"] for l in (ROOT / "curated" / "builds.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {}
    for b in args:
        res = analyse(b)
        if res is None:
            print(f"{b}: no libmpr.so")
            continue
        (OUT_DIR / f"media_rate_{b}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf8")
        rc = res["rate_check"]
        if not rc:
            print(f"{b}: libmpr.so {res['libmpr_sha256'][:16]} has no RateCheck::GetMediaTransferRateInh")
            summary[b] = None
            continue
        rp = res["remove_patch"]
        print(f"{b}: libmpr.so {res['libmpr_sha256'][:16]}  GetMediaTransferRateInh {rc['GetMediaTransferRateInh']['va']} "
              f"(+{rc['GetMediaTransferRateInh']['size']}), helper {rc['compare_helper']['va']}, drive info rate +{rc['drive_info_offsets']['transferRate']:#x} "
              f"fs +{rc['drive_info_offsets']['filesystemType']:#x}")
        for t, v in res["check_types"].items():
            print(f"   type {t}: fs4 {v['fs4']}; fs3 {v['fs3']}")
        print(f"   remove patch: {len(rp['sites'])} sites {[s['va'] for s in rp['sites']]} verify {rp['verify']}")
        for k, c in type_census(res).items():
            print(f"   {k}: rows by type {c}")
        summary[b] = {"sites": [s["va"] for s in rp["sites"]], "stock": [s["stock"] for s in rp["sites"]], "verify": rp["verify"]["ok"] if rp["verify"] else None,
                      "function": rc["GetMediaTransferRateInh"]["va"], "sha": res["libmpr_sha256"]}
        if design:
            print("   design written:", write_design(res, design))
    if len(args) > 1:
        (OUT_DIR / "media_rate_summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
