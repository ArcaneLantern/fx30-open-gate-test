"""Designs fx30flash_v1 (superseded) and fx30flash_v2 (session HS1): the data changes that let an FX30 6.01 use an external flash with its
electronic shutter, in the running camera's memory. Read-only on firmware; writes modding/designs/fx30flash_v1.json and fx30flash_v2.json.

  python -I -B build/build_fx30_flash.py

Three groups of sites (reference/hotshoe_flash.md, modding/FX30_FLASH_ENABLE.md):
  R  exclusion rules (appFw.so data segment, RELRO). The two rules on the derived key HAITA_setting_still_shutter_type_setting_px_shift_
     multi_shoot (0x29f) each have one 8-byte pointer per key value to their action list:
       rule 0x3dad040 (target FUNC ..._electronic_for_haita 0xc36): slot for ELECTRONIC 0x48bcd90 -> info 0x3def370   v2: null
       rule 0x3da8f50 (target FUNC ..._invalid_for_haita 0xc37):    slot for ELECTRONIC 0x48baaa8 = null           v2: -> info 0x3e4fd70
                                                                    (the list it already has for pixel shift on)
     So with the electronic shutter the engine calls "invalid", as the ZV-E1 does under NO_RESTRICTION (F1102), instead of "electronic".
     Both slots are relocated pointers: in memory they hold the load base plus the value; the helper adds the base it finds in /proc/self/maps.
     v1 changed the two ids inside the kind-4 action (0x32badd4, 0x32badd8); the engine reads only the action's kind byte and calls the
     FUNC that is the rule's target, so v1's R change does nothing (build/emu_exclusion_fx30.py, scenario B). v1 is kept for the record.
  M  menu flags (appFw.so RELRO): the FX30's own column (7, class LAX) of the flash menu items, choices and pages copied from the FX3
     build's column 6 (F1106); Wireless Flash (348) stays hidden.
  S  shoe-ID table: libObj.so's InfraHotshoe instance (pointer at libObj 0x2cde00, vtable 0x251c38) keeps a heap copy of stored setting
     0x01120004 (42 entries of 32 bytes, words 0 and 1 swapped: {shoe ID, key code}) at instance +0x60, count at +0x28. Word 1 of entries
     17, 19 and 35 (shoe IDs 0x50505, 0x10505, 0x50504) goes from 0x04ffffff (not supported) to the FX3's 0x04000012/14/24 (F1104).
Guards: the ELF headers, every byte beside the sites, both rules' headers and other slots, both action lists, the libObj code that builds
and reads the table, and the whole 42-entry table.
"""
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import exclusion_rules_xbuild as xr  # noqa: E402
import locate_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = "fx30_601"
MENU_ITEMS = {345, 346, 347, 352, 353, 354, 355}       # Flash Mode, Flash Comp., Exp.comp.set, Red Eye, Ext. Flash Set. (+2)
SHOE = [(0x230, 0x00050505, 0x04000012, "II_STROBE"), (0x270, 0x00010505, 0x04000014, "ALPHA_STROBE"),
        (0x470, 0x00050504, 0x04000024, "II_STROBE_REMOTE_TRIGGER")]
RULE_E, RULE_I = 0x3DAD040, 0x3DA8F50                  # "electronic" (target 0xc36) and "invalid" (target 0xc37), both on key 0x29f
SLOT_E, SLOT_I, INFO_E, INFO_I = 0x48BCD90, 0x48BAAA8, 0x3DEF370, 0x3E4FD70
ACT_E, ACT_I = 0x32BADD0, 0x3394358
OBJ = {"inst_ptr": 0x2CDE00, "refcount": 0x2CDDF8, "vtable_point": 0x251C38, "count_off": 0x28, "array_off": 0x60, "entry": 32, "entries": 42}
OBJ_CODE = {0xBC34C: "KeyConfigAlloc", 0xBC308: "the lookup by shoe ID", 0xBEA34: "infra_hotshoe_init", 0xBE958: "get-or-create",
            0xBD334: "infra_hotshoe_exit", 0xBE464: "constructor"}


def relocs(data):
    out = {}
    for sec in ELFFile(io.BytesIO(data)).iter_sections():
        if sec.header.sh_type == "SHT_RELA":
            for r in sec.iter_relocations():
                out[r["r_offset"]] = (r["r_info_type"], r["r_addend"])
    return out


class Lib:
    def __init__(self, path):
        self.d = Path(path).read_bytes()
        self.sha = hashlib.sha256(self.d).hexdigest()
        self.rel = relocs(self.d)
        e = ELFFile(io.BytesIO(self.d))
        self.loads = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in e.iter_segments() if s["p_type"] == "PT_LOAD"]

    def off(self, va):
        for v, o, n in self.loads:
            if v <= va < v + n:
                return o + va - v
        raise ValueError(hex(va))

    def seg(self, va):
        return 0 if va < self.loads[0][2] else 1

    def raw(self, va, n):
        o = self.off(va)
        return self.d[o:o + n]

    def ptr(self, va):
        """The pointer at va as the loader leaves it: ("rel", addend) for a relative relocation, ("null", 0) for a zero with no relocation."""
        r = self.rel.get(va)
        if r:
            assert r[0] == 1027, (hex(va), r)
            return ("rel", r[1])
        assert self.raw(va, 8) == bytes(8), (hex(va), self.raw(va, 8).hex())
        return ("null", 0)


def entry(lib, kind, va, label, new=None, ptr=False, n=None):
    """One table entry: a guard (kind 0) or a site (kind 1). Literal bytes, or an 8-byte pointer (stock/new given as ("rel", addend) / ("null", 0))."""
    e = {"kind": kind, "va": hex(va), "seg": lib.seg(va), "file_off": hex(lib.off(va)), "label": label}
    if ptr:
        e.update(len=8, pointer=True, stock=lib.ptr(va), new=new if kind else None)
        assert all(not lib.rel.get(va + k) for k in range(1, 8))
    else:
        b = lib.raw(va, n)
        e.update(len=n, pointer=False, stock=b.hex(), new=(new.hex() if kind else None))
        if kind:
            assert len(new) == n and new != b
        for k in range(n):                             # a literal entry must not overlap a relocated word: memory would differ from the file
            assert not any(a <= va + k < a + 8 for a in lib.rel if a in range(va - 7, va + n)), (hex(va), label)
    return e


def main():
    app = Lib(locate_file.locate(BUILD, "appFw.so"))
    obj = Lib(common.EXTRACTED / BUILD / "0700_part_image/dev/nflasha15/lib/libObj.so")
    t = xr.decode(BUILD)
    assert t["name"][0xC36] == "FUNC_set_setting_still_shutter_type_electronic_for_haita"
    assert t["name"][0xC37] == "FUNC_set_setting_still_shutter_type_invalid_for_haita"
    key = t["ids"]["PRM_HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot"]
    assert key == 0x29F
    # the two rules: {tab, target, source}, and their per-value slots (NOT_SET, ELECTRONIC, PX_SHIFT_ON)
    for rule, tgt, tab in ((RULE_E, 0xC36, 0x48BCD88), (RULE_I, 0xC37, 0x48BAAA0)):
        assert app.ptr(rule) == ("rel", tab) and struct.unpack("<ii", app.raw(rule + 8, 8)) == (tgt, key), hex(rule)
    assert [app.ptr(0x48BCD88 + 8 * k) for k in range(3)] == [("null", 0), ("rel", INFO_E), ("null", 0)]
    assert [app.ptr(0x48BAAA0 + 8 * k) for k in range(3)] == [("null", 0), ("null", 0), ("rel", INFO_I)]
    assert app.ptr(INFO_E) == ("rel", ACT_E) and struct.unpack("<I", app.raw(INFO_E + 8, 4))[0] == 1
    assert app.ptr(INFO_I) == ("rel", ACT_I) and struct.unpack("<I", app.raw(INFO_I + 8, 4))[0] == 1
    assert app.raw(ACT_E, 12) == bytes.fromhex("04020000360c0000360c0000") and app.raw(ACT_I, 12) == bytes.fromhex("04020000370c0000370c0000")

    R = [entry(app, 0, 0, "appFw.so ELF header", n=16),
         entry(app, 0, ACT_E, "the 'electronic' rule's kind-4 action", n=12),
         entry(app, 0, ACT_I, "the 'invalid' rule's kind-4 action", n=12),
         entry(app, 0, RULE_E, "rule 0x3dad040: its slot table", ptr=True), entry(app, 0, RULE_E + 8, "rule 0x3dad040: target 0xc36, source 0x29f", n=8),
         entry(app, 0, RULE_I, "rule 0x3da8f50: its slot table", ptr=True), entry(app, 0, RULE_I + 8, "rule 0x3da8f50: target 0xc37, source 0x29f", n=8),
         entry(app, 0, 0x48BCD88, "rule 0x3dad040, slot NOT_SET", ptr=True), entry(app, 0, 0x48BCD98, "rule 0x3dad040, slot PX_SHIFT_ON", ptr=True),
         entry(app, 0, 0x48BAAA0, "rule 0x3da8f50, slot NOT_SET", ptr=True), entry(app, 0, 0x48BAAB0, "rule 0x3da8f50, slot PX_SHIFT_ON", ptr=True),
         entry(app, 0, INFO_E, "info 0x3def370: its action list", ptr=True), entry(app, 0, INFO_E + 8, "info 0x3def370: one action", n=4),
         entry(app, 0, INFO_I, "info 0x3e4fd70: its action list", ptr=True), entry(app, 0, INFO_I + 8, "info 0x3e4fd70: one action", n=4),
         entry(app, 1, SLOT_E, "rule 0x3dad040 ('electronic'), slot ELECTRONIC: -> info 0x3def370, becomes null", new=("null", 0), ptr=True),
         entry(app, 1, SLOT_I, "rule 0x3da8f50 ('invalid'), slot ELECTRONIC: null, becomes -> info 0x3e4fd70", new=("rel", INFO_I), ptr=True)]

    menu = json.loads((ROOT / "evidence" / "hotshoe" / "menu_flash_fx30_601.json").read_text(encoding="utf8"))
    M, seen = [], set()

    def add_flag(label, flags):
        own, fx3 = flags["LAX"], flags["ALCIN_UUD"]
        if own["value"] != 0 or fx3["value"] == 0 or own["va"] in seen:
            return
        va = int(own["va"], 16)
        assert app.off(va) == int(own["file_offset"], 16) and app.raw(va, 1) == b"\0"
        assert app.raw(int(fx3["va"], 16), 1)[0] == fx3["value"]
        seen.add(own["va"])
        reloc = lambda a: any(r <= a < r + 8 for r in range(a - 7, a + 1) if r in app.rel)   # byte a lies in a relocated word
        lo = va
        while lo > va - 8 and not reloc(lo - 1):
            lo -= 1
        hi = va + 1
        while hi < va + 9 and not reloc(hi):
            hi += 1
        assert not reloc(va)
        if lo < va:
            M.append(entry(app, 0, lo, label + ": the %d bytes before" % (va - lo), n=va - lo))
        M.append(entry(app, 1, va, label + ": column 7 (LAX) from column 6 (FX3)", new=bytes([fx3["value"]]), n=1))
        if hi > va + 1:
            M.append(entry(app, 0, va + 1, label + ": the %d bytes after" % (hi - va - 1), n=hi - va - 1))
    for it in menu["items"]:
        if it["number"] in MENU_ITEMS:
            add_flag(f"{it['kind']} {it['number']} '{it['title']}'", it["flags"])
            if it["number"] == 345:
                for ch in it.get("choices") or []:
                    add_flag(f"choice {ch.get('option')} '{ch.get('text')}' of Flash Mode", ch["flags"])
    assert sum(e["kind"] for e in M) == 12

    sys.path.append(str(common.CAMERA_RE / "a7iv" / "sony-a7iv-feature-research" / "scripts"))
    import bk4
    prof = bk4.profile_paths(common.EXTRACTED / BUILD / "update")
    values = {bytes(bk4.load_backup(p)[0].props[0x01120004].data) for p in prof}
    assert len(values) == 1, "the regional profiles disagree"
    value = values.pop()
    assert value[:4] == b"BIN!" and value[12:16] == b"CNF!" and struct.unpack_from("<I", value, 8)[0] == OBJ["entries"]
    heap = bytearray()
    for i in range(OBJ["entries"]):                     # KeyConfigAlloc's copy: words 0 and 1 swapped, 2..7 as stored
        w = list(struct.unpack_from("<8I", value, 0x10 + 32 * i))
        heap += struct.pack("<8I", w[1], w[0], *w[2:])
    assert value[0x10 + 32 * OBJ["entries"]:0x10 + 32 * OBJ["entries"] + 4] == b"FIN!"
    S = []
    for off, ident, key_code, name in SHOE:
        i = (off - 0x10) // 32
        k, sid = struct.unpack_from("<II", value, off)
        assert (k, sid) == (0x04FFFFFF, ident) and struct.unpack_from("<II", heap, 32 * i) == (ident, 0x04FFFFFF)
        S.append({"entry": i, "shoe_id": hex(ident), "heap_off": hex(32 * i + 4), "setting_off": hex(off), "stock": "ffffff04",
                  "new": struct.pack("<I", key_code).hex(), "input": name})
    O = [entry(obj, 0, 0, "libObj.so ELF header", n=16)] + [entry(obj, 0, va, "libObj.so " + what + " (first 16 bytes)", n=16) for va, what in OBJ_CODE.items()]
    assert obj.rel.get(0x2625D0) == (1027, 0x251C28), "the constructor's vtable slot"
    assert OBJ["vtable_point"] == 0x251C28 + 0x10

    base = {"build": BUILD, "generated_by": "build/build_fx30_flash.py", "library": "appFw.so",
            "artifact_sha256": {"appFw.so": app.sha, "libObj.so": obj.sha}, "menu_class_column": 7}
    v2 = dict(base, design="fx30flash_v2",
              title="FX30 6.01: external flash with the electronic shutter, in memory: the ZV-E1's 'invalid' path for the shutter-type rules "
                    "(two pointer slots), the flash menus of class LAX (12 flag bytes), and the three flash shoe IDs in libObj.so's heap copy "
                    "of the shoe table (three words)",
              rule_slots=R, menu_flags=M, libobj_guards=O, libobj_chain=dict({k: (hex(v) if isinstance(v, int) and v > 64 else v) for k, v in OBJ.items()}),
              shoe_table_heap_stock=bytes(heap).hex(), shoe_sites=S,
              takes_effect="rule slots: at the next change of the derived key, i.e. after the camera goes to Movie (or S&Q, or Auto) and back to "
                           "P/A/S/M (build/emu_exclusion_fx30.py scenarios G-J); menu flags: at the next menu display; shoe IDs: when a flash is "
                           "attached or switched on (the lookup reads the heap table each time)",
              write_order="shoe table, menu flags, rule slots; put back in reverse",
              lasts="until the camera's software restarts (battery out); libObj.so's table is not rebuilt while the camera runs (the instance "
                    "is created at start-up and kept)",
              summary={"rule_sites": sum(e["kind"] for e in R), "rule_guards": sum(1 - e["kind"] for e in R),
                       "menu_sites": sum(e["kind"] for e in M), "menu_guards": sum(1 - e["kind"] for e in M),
                       "shoe_sites": len(S), "libobj_guards": len(O), "shoe_table_bytes": len(heap)},
              not_covered=["whether the FX30's shoe hardware carries the flash lines (U100)",
                           "the coprocessor's start time for an electronic-shutter still (U102)",
                           "a shutter-speed limit with flash on (F1108, U106): set 1/8 s or slower by hand",
                           "wireless flash (stays forced off)"],
              status="built as kit step F18/F19/F20 (helper_fx30/fx30flash.c); emulated; NOT RUN ON A CAMERA")
    dst = ROOT / "modding" / "designs" / "fx30flash_v2.json"
    dst.write_text(json.dumps(v2, indent=1) + "\n", encoding="utf8", newline="\n")
    # v1, for the record (superseded)
    p1 = ROOT / "modding" / "designs" / "fx30flash_v1.json"
    if p1.is_file():
        v1 = json.loads(p1.read_text(encoding="utf8"))
        v1["status"] = ("SUPERSEDED by fx30flash_v2 (2026-11-27): its two rule sites (the ids inside kind-4 action 0x32badd0) are never read; the engine "
                        "reads only the action's kind and calls the FUNC that is the rule's target (build/emu_exclusion_fx30.py, scenario B)")
        p1.write_text(json.dumps(v1, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"fx30flash_v2: {v2['summary']} -> {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
