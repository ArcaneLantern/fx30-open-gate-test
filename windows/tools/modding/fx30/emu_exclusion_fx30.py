"""Run the FX30 6.01 exclusion manager of appFw.so in Unicorn to see whether design fx30flash_v1's rule change, written into memory
while the camera is already running, frees Flash Mode after a switch to Movie and back (session HS1, 2026-11-27;
modding/FX30_FLASH_ENABLE.md, findings F1102 and F1140).

Made from build/emu_exclusion_manager.py (the A7 IV run, finding F504), with this build's addresses:
  init 0x2703004, run_exclusion 0x27035d4      found by the function-name string and by the same constants as the A7 IV's
  state table 0x820d0b0, 24 bytes per entry, 0xc61 entries (parameters 0..0x9bf and the FUNC pseudo-parameters 0x9c0..0xc60)
  inhibit counters 0x81f65f8 (4 bytes per value id); type table through the pointer at 0x477a7d8 (8 bytes per entry: type, number)
  PLT 0x1591ce0..0x1594ab0, stubs named from .rela.plt: new, delete, memset, memmove, memcpy and need_rehash are stood in for; every
  other library call returns 0 and is counted
The engine object is built by hand as in the A7 IV run (accessor at +0, an empty hash map at +0x10). The model accessor is a table of
stubs; every call is logged. A FUNC pseudo-parameter whose value changes makes the engine call accessor slot 3 with the function's
number (run_exclusion: type 8). The model is stood in for at that one point: the three FUNC_set_setting_still_shutter_type_*_for_haita
calls set setting_still_shutter_type_re_throwing to MECHANICAL / ELECTRONIC / INVALID, as their names say, and the engine runs again,
as it would when the model reports the change. Nothing else of the model is modelled.

Scenarios (each from init):
  A  stock: start in still M with the electronic shutter, then Movie, then still M again
  B  the patch written after start-up in still M (the two ids of action 0x32badd0 = 0xc37), then Movie, then still M
  C  the patch written after start-up, no mode change
  D  the patch, Movie, still M, then the put back (0xc36), Movie, still M
For each step: the re-throwing key, the derived key, Flash Mode's value and its inhibit counters, Wireless Flash's, and the FUNC calls.

  work\\venv\\Scripts\\python.exe -I -B build\\emu_exclusion_fx30.py        writes evidence/hotshoe/exclusion_engine_fx30_emu.json
"""
import collections
import io
import json
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as R

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402
import exclusion_rules_xbuild as xr  # noqa: E402

BUILD = "fx30_601"
SEG0_END, RW_VA, RW_OFF, RW_FILESZ, RW_MEMSZ = 0x3D1392D, 0x3D23D38, 0x3D13D38, 0xE4AA00, 0x60A5CC0
TOP = (RW_VA + RW_MEMSZ + 0xFFFF) & ~0xFFFF
HEAP, HEAP_SIZE, STACK, RET = 0x10000000, 0x4000000, 0x9F80000, 0x9FF0000
STUBS = 0x9FE0000
INIT, RUN = 0x2703004, 0x27035D4
N, STATE, INH, TYPE_PTR = 0xC61, 0x820D0B0, 0x81F65F8, 0x477A7D8
PLT_LO, PLT_HI = 0x1591CE0, 0x1594AB0
ACTION = 0x32BADD0                                  # the rule's kind-4 action: {4, 2, 0, 0, 0xc36, 0xc36}; the engine reads only its kind byte
RULE_TARGET = 0x3DAD048                             # the rule 0x3dad040's target, +8: the FUNC pseudo-parameter the engine sets (0xc36)
# Design v2 (fx30flash_v2): the two rules on the derived key 0x29f, per-value slots (8-byte pointers, relocated, in RELRO):
SLOT_ELEC = 0x48BCD90                               # rule 0x3dad040 ("electronic"), value ELECTRONIC: -> info 0x3def370 (stock); v2: 0
SLOT_INV = 0x48BAAA8                                # rule 0x3da8f50 ("invalid"), value ELECTRONIC: 0 (stock); v2: -> info 0x3e4fd70 (its pixel-shift list)
INFO_ELEC, INFO_INV = 0x3DEF370, 0x3E4FD70
NONE = 0x80000000


def foff(va):
    return va - 0x10000 if va >= RW_VA else va


class Engine:
    def __init__(self, app, plt):
        self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.mem_map(0, TOP)
        uc.mem_map(0x9F00000, 0x100000)
        uc.mem_map(HEAP, HEAP_SIZE)
        uc.mem_write(0, app[:SEG0_END])
        uc.mem_write(RW_VA, app[RW_OFF:RW_OFF + RW_FILESZ])
        e = ELFFile(io.BytesIO(app))
        n_rel = 0
        for sec in e.iter_sections():                  # relative relocations at load base 0: the word is the addend
            if sec.header.sh_type == "SHT_RELA" and sec.name == ".rela.dyn":
                for r in sec.iter_relocations():
                    if r["r_info_type"] == 1027:
                        uc.mem_write(r["r_offset"], struct.pack("<Q", r["r_addend"]))
                        n_rel += 1
        self.n_rel = n_rel
        uc.reg_write(R.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        self.brk = HEAP + 0x1000
        self.calls, self.unknown = [], collections.Counter()
        x = lambda n: uc.reg_read(getattr(R, f"UC_ARM64_REG_X{n}"))
        ret = lambda v=None: (uc.reg_write(R.UC_ARM64_REG_X0, v) if v is not None else None, uc.reg_write(R.UC_ARM64_REG_PC, x(30)))

        def hook(u, addr, size, _):
            if PLT_LO <= addr < PLT_HI:
                k = plt.get(addr, "?")
                if k in ("_Znwm", "_Znam"):
                    p = self.brk
                    self.brk += (x(0) + 0x1F) & ~0xF
                    ret(p)
                elif k in ("_ZdlPv", "_ZdlPvm", "_ZdaPv", "_ZdaPvm"):
                    ret()
                elif k == "memset":
                    u.mem_write(x(0), bytes([x(1) & 0xFF]) * x(2))
                    ret(x(0))
                elif k in ("memmove", "memcpy"):
                    if x(2):
                        u.mem_write(x(0), bytes(u.mem_read(x(1), x(2))))
                    ret(x(0))
                elif k.endswith("_M_need_rehashEmmm"):
                    u.reg_write(R.UC_ARM64_REG_X1, 0)
                    ret(0)
                elif "throw" in k or k == "_ZSt9terminatev":
                    raise RuntimeError("the firmware called %s" % k)
                else:
                    self.unknown[k] += 1
                    ret(0)
            elif STUBS <= addr < STUBS + 0x400:
                self.calls.append(((addr - STUBS) // 8, x(1) & 0xFFFFFFFF, x(2) & 0xFFFFFFFF, x(3) & 0xFF))
                ret(0)
            elif addr == RET:
                u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, hook, begin=PLT_LO, end=PLT_HI)
        uc.hook_add(UC_HOOK_CODE, hook, begin=STUBS, end=STUBS + 0x400)
        uc.hook_add(UC_HOOK_CODE, hook, begin=RET, end=RET)
        self.obj = self.alloc(0x200)
        acc = self.alloc(0x10)
        vt = self.alloc(0x200)
        uc.mem_write(vt, b"".join(struct.pack("<Q", STUBS + 8 * i) for i in range(0x40)))
        uc.mem_write(acc, struct.pack("<Q", vt))
        uc.mem_write(self.obj, struct.pack("<Q", acc))
        m = self.obj + 0x10
        uc.mem_write(m, struct.pack("<QQQQfIQQ", m + 0x30, 1, 0, 0, 1.0, 0, 0, 0))
        self.stocker = self.alloc(0x400)

    def alloc(self, n):
        p = self.brk
        self.brk += (n + 0x1F) & ~0xF
        return p

    def call(self, fn, *args, limit=400_000_000):
        for i, a in enumerate(args):
            self.uc.reg_write(getattr(R, f"UC_ARM64_REG_X{i}"), a)
        self.uc.reg_write(R.UC_ARM64_REG_SP, STACK)
        self.uc.reg_write(R.UC_ARM64_REG_X30, RET)
        self.uc.emu_start(fn, RET, count=limit)
        if self.uc.reg_read(R.UC_ARM64_REG_PC) != RET:
            raise RuntimeError(f"did not return: pc {self.uc.reg_read(R.UC_ARM64_REG_PC):#x}")

    def state(self, p):
        return struct.unpack_from("<4i", bytes(self.uc.mem_read(STATE + 24 * p, 16)))

    def set_from_model(self, p, v):
        self.uc.mem_write(STATE + 24 * p + 4, struct.pack("<I", v))
        self.uc.mem_write(STATE + 24 * p + 0x10, b"\x01")

    def inhibited(self, v):
        return struct.unpack("<i", bytes(self.uc.mem_read(INH + 4 * v, 4)))[0]

    def action_ids(self):
        return struct.unpack("<3I", bytes(self.uc.mem_read(ACTION, 12)))

    def write_ids(self, fid):
        self.uc.mem_write(ACTION + 4, struct.pack("<II", fid, fid))

    def target(self):
        return struct.unpack("<I", bytes(self.uc.mem_read(RULE_TARGET, 4)))[0]

    def write_target(self, fid):
        self.uc.mem_write(RULE_TARGET, struct.pack("<I", fid))

    def slots(self):
        return struct.unpack("<Q", bytes(self.uc.mem_read(SLOT_ELEC, 8)))[0], struct.unpack("<Q", bytes(self.uc.mem_read(SLOT_INV, 8)))[0]

    def write_slots(self, elec, inv):                  # load base 0 here: a slot holds the virtual address itself
        self.uc.mem_write(SLOT_ELEC, struct.pack("<Q", elec))
        self.uc.mem_write(SLOT_INV, struct.pack("<Q", inv))


def main():
    app = locate_file.locate(BUILD, "appFw.so").read_bytes()
    t = xr.decode(BUILD)
    assert t["n_par"] == N, hex(t["n_par"])
    e0 = ELFFile(io.BytesIO(app))
    plt_sec, rp, ds = e0.get_section_by_name(".plt"), e0.get_section_by_name(".rela.plt"), e0.get_section_by_name(".dynsym")
    plt = {plt_sec["sh_addr"] + 32 + 16 * i: ds.get_symbol(r["r_info_sym"]).name for i, r in enumerate(rp.iter_relocations())}
    assert plt[0x1591F30] == "memset" and plt[0x15940D0] == "_Znwm"
    assert app[ACTION:ACTION + 12] == bytes.fromhex("04020000360c0000360c0000")
    assert struct.unpack_from("<II", app, foff(RULE_TARGET)) == (0xC36, 0x29F)          # target FUNC 0xc36, source the derived key 0x29f
    assert struct.unpack_from("<QQ", app, foff(SLOT_ELEC - 8)) == (0, INFO_ELEC)         # NOT_SET none, ELECTRONIC -> the "electronic" action list
    assert struct.unpack_from("<QQQ", app, foff(SLOT_INV - 8)) == (0, 0, INFO_INV)       # NOT_SET none, ELECTRONIC none, PX_ON -> the "invalid" list
    assert struct.unpack_from("<II", app, foff(0x3DA8F58)) == (0xC37, 0x29F)
    type_tab = struct.unpack_from("<Q", app, foff(TYPE_PTR))[0]
    typ = lambda p: struct.unpack_from("<ii", app, foff(type_tab + 8 * p))
    pid = lambda n: t["ids"]["PRM_" + n]
    fid = lambda n: t["ids"]["FUNC_" + n]
    rng = lambda p: t["rng"][p][:2]

    def vid(param, text):
        a, b = rng(pid(param))
        hits = [v for v in range(a, b + 1) if t["name"][v].endswith(text)]
        assert len(hits) == 1, (param, text)
        return hits[0]

    def vname(p, v):
        if v in (-0x80000000, NONE):
            return "none"
        return xr.short(t, v).replace(xr.short(t, p) + "_", "")
    RT, HK, FM, WF = pid("setting_still_shutter_type_re_throwing"), pid("HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot"), \
        pid("setting_flash_mode"), pid("setting_wireless_flash")
    funcs = {fid("set_setting_still_shutter_type_%s_for_haita" % k): k for k in ("mechanical", "electronic", "invalid")}
    number_of = {typ(f)[1]: f for f in funcs}                     # the number the engine hands the model for each FUNC
    assert all(typ(f)[0] == 8 for f in funcs), [typ(f) for f in funcs]
    re_value = {"mechanical": vid("setting_still_shutter_type_re_throwing", "_MECHANICAL"),
                "electronic": vid("setting_still_shutter_type_re_throwing", "_ELECTRONIC"),
                "invalid": vid("setting_still_shutter_type_re_throwing", "_INVALID")}
    STILL_M, MOVIE_M = vid("exposure_mode", "EXPOSURE_MODE_STILL_M"), vid("exposure_mode", "EXPOSURE_MODE_MOVIE_M")
    STILL_A = vid("exposure_mode", "EXPOSURE_MODE_STILL_A")
    ELEC = vid("setting_still_shutter_type", "STILL_SHUTTER_TYPE_ELECTRONIC")
    PX_OFF = vid("setting_px_shift_multi_shoot", "PX_SHIFT_MULTI_SHOOT_OFF")
    FILL = vid("setting_flash_mode", "FLASH_MODE_VALUE_FILL_FLASH")
    WL_OFF = vid("setting_wireless_flash", "WIRELESS_FLASH_VALUE_OFF")
    SILENT_ON = vid("setting_silent_mode", "SILENT_MODE_ON")

    def settle(eng, log):
        """run_exclusion, then the model's answer to each FUNC call, until nothing more is called (at most 6 rounds)."""
        for _ in range(6):
            k = len(eng.calls)
            eng.call(RUN, eng.obj, eng.stocker)
            fcalls = [number_of[a1] for slot, a1, a2, a3 in eng.calls[k:] if slot == 3 and a1 in number_of]
            for f in fcalls:
                log.append("FUNC_" + xr.short(t, f))
                eng.set_from_model(RT, re_value[funcs[f]])
            if not fcalls:
                return
        raise RuntimeError("the FUNC calls did not settle")

    def snap(eng, label, log):
        fm_lo, fm_hi = rng(FM)
        wf_lo, wf_hi = rng(WF)
        row = {"step": label, "func_calls": list(log),
               "re_throwing": vname(RT, eng.state(RT)[2]), "derived_key": vname(HK, eng.state(HK)[2]),
               "flash_mode": vname(FM, eng.state(FM)[2]),
               "flash_mode_inhibited": {vname(FM, v): eng.inhibited(v) for v in range(fm_lo, fm_hi + 1) if eng.inhibited(v)},
               "flash_mode_param_inhibit": eng.inhibited(FM),
               "wireless_flash": vname(WF, eng.state(WF)[2]),
               "wireless_inhibited": {vname(WF, v): eng.inhibited(v) for v in range(wf_lo, wf_hi + 1) if eng.inhibited(v)},
               "wireless_param_inhibit": eng.inhibited(WF), "action_ids": [hex(v) for v in eng.action_ids()[1:]], "rule_target": hex(eng.target()),
               "slots": [hex(v) for v in eng.slots()]}
        log.clear()
        return row

    def start(eng, log):
        eng.call(INIT, eng.obj)
        eng.call(RUN, eng.obj, eng.stocker)
        for p, v in ((pid("exposure_mode"), STILL_M), (pid("setting_still_shutter_type"), ELEC), (pid("setting_px_shift_multi_shoot"), PX_OFF),
                     (FM, FILL), (WF, WL_OFF), (pid("setting_silent_mode"), SILENT_ON)):
            eng.set_from_model(p, v)
        settle(eng, log)

    def mode(eng, log, v):
        eng.set_from_model(pid("exposure_mode"), v)
        settle(eng, log)

    out = {"about": "The FX30 6.01 exclusion manager of appFw.so run in Unicorn. Generated by build/emu_exclusion_fx30.py; see its header for what "
                    "is stood in for. Flash Mode is stored as Fill-flash so that a force to Flash Off shows.", "scenarios": {}}
    scen = {
        "A_stock": [("start, still M, electronic shutter", None), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "B_action_ids_only_then_mode_switch": [("start, still M, electronic shutter", None), ("action ids 0xc37 (design v1)", "ids"), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "C_target_then_mode_switch": [("start, still M, electronic shutter", None), ("target + ids 0xc37 (design v2)", "patch"), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "D_target_no_mode_switch": [("start, still M, electronic shutter", None), ("target + ids 0xc37 (design v2)", "patch"), ("run_exclusion again", "run")],
        "E_target_then_put_back": [("start, still M, electronic shutter", None), ("target + ids 0xc37 (design v2)", "patch"), ("Movie M", MOVIE_M), ("still M", STILL_M),
                                   ("put back (0xc36)", "putback"), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "F_target_then_still_mode_change": [("start, still M, electronic shutter", None), ("target + ids 0xc37 (design v2)", "patch"),
                                            ("still A", STILL_A), ("still M", STILL_M)],
        "G_slots_then_mode_switch": [("start, still M, electronic shutter", None), ("slots (fx30flash_v2)", "slots"), ("Movie M", MOVIE_M), ("still M", STILL_M),
                                     ("still A", STILL_A), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "H_slots_no_mode_switch": [("start, still M, electronic shutter", None), ("slots (fx30flash_v2)", "slots"), ("run_exclusion again", "run"), ("still A", STILL_A)],
        "I_slots_then_put_back": [("start, still M, electronic shutter", None), ("slots (fx30flash_v2)", "slots"), ("Movie M", MOVIE_M), ("still M", STILL_M),
                                  ("slots put back", "slots_back"), ("still A", STILL_A), ("Movie M", MOVIE_M), ("still M", STILL_M)],
        "J_slots_applied_in_movie": [("start, still M, electronic shutter", None), ("Movie M", MOVIE_M), ("slots (fx30flash_v2)", "slots"), ("still M", STILL_M)],
    }
    for name, steps in scen.items():
        eng = Engine(app, plt)
        log, rows = [], []
        for label, what in steps:
            if what is None:
                start(eng, log)
            elif what == "ids":
                eng.write_ids(0xC37)
            elif what == "patch":
                eng.write_target(0xC37)
                eng.write_ids(0xC37)
            elif what == "putback":
                eng.write_target(0xC36)
                eng.write_ids(0xC36)
            elif what == "slots":
                eng.write_slots(0, INFO_INV)
            elif what == "slots_back":
                eng.write_slots(INFO_ELEC, 0)
            elif what == "run":
                settle(eng, log)
            else:
                mode(eng, log, what)
            rows.append(snap(eng, label, log))
        out["scenarios"][name] = {"steps": rows, "unknown_library_calls": dict(eng.unknown), "relocations": eng.n_rel}
        print("\n" + name)
        for r in rows:
            print("  %-34s re_throwing %-10s key %-17s flash %-11s param-inhibit %d  values %s  wireless-inhibit %d  funcs %s" % (
                r["step"], r["re_throwing"].replace("STILL_SHUTTER_TYPE_RE_THROWING_", ""), r["derived_key"].replace("STILL_SHUTTER_TYPE_", ""),
                r["flash_mode"].replace("FLASH_MODE_VALUE_", ""), r["flash_mode_param_inhibit"],
                sorted(k.replace("FLASH_MODE_VALUE_", "") for k in r["flash_mode_inhibited"]), r["wireless_param_inhibit"],
                [c.replace("FUNC_FUNC_set_setting_still_shutter_type_", "").replace("_for_haita", "") for c in r["func_calls"]]))
        if eng.unknown:
            print("  unknown library calls:", dict(eng.unknown))
    dst = ROOT / "evidence/hotshoe/exclusion_engine_fx30_emu.json"
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("\n->", dst.relative_to(ROOT))


if __name__ == "__main__":
    main()
