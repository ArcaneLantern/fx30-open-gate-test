"""Build `outsz2560_fx30_v1`: the FX30 6.01 (fx30_601) counterpart of the A7 IV's working `outsz2560_v1` (FX30 port, 2026-11-26).

  C:/Python313/python.exe -B build/build_ram_words_fx30.py      writes modding/designs/outsz2560_fx30_v1.json and _pokes_ram.txt

One word of coprocessor RAM, the 4K movie request's output size: 3840 x 2160 -> 3840 x 2560. How the FX30's address was found:
  - The movie size table is filled at run time by 0x4644bc, the A7 IV's 0x4293c8 relinked (match_thumb exact over 96 bytes; diff_consts
    aligns 275 of 283 instructions: relocated targets, the base 0x143c734 -> 0x155d3bc, and the fields after +0x120 4 bytes earlier).
    build/emu_size_table.py fx30_601 runs it alone (calls stubbed, state zero): table at base + 0x50 = 0x155d40c, and its 16 entries equal
    the A7 IV's (asserted below).
  - The reader that picks the entry for a movie request: the A7 IV's 0x4456b4 (outsz2560_v1's reader) is a case of a tbh switch at 0x44566a
    on the request's size class [r6 + 0x74]; the FX30's is the same code at 0x480a36 on [r6 + 0x7c] (match_thumb 0x4456b4 -> 0x480a80).
    Both switches are decoded below from the files: case 3 (UHD) loads base + 0x88 in both, and cases 0 to 12 pick the same entries (case 0 loads none in either).
  - The output buffer of that entry, memory id 0x2d9, is 9 units of 13,271,040 bytes in the FX30's DmmCfg.bin, as on the A7 IV; a 3840 x 2560
    picture at format code 2 (x 1.25 bytes per pixel, read on the A7 IV camera in its stock 4K, not on an FX30) is 12,288,000 bytes. The FX3,
    whose id 0x2d9 is the same 9 x 13,271,040, records 3840 x 2560 on the camera (2026-11-24).
  - The movie raw write buffer of the same table rows, memory id 0x43e, needs no change on the FX30 (modding/FX30_PORT_DMM_SIZE.md).
Guards, as on the A7 IV: the entry before (3840, 2160, memory id 0x43e) and this entry's memory id (0x2d9).
Design only; nothing has run on an FX30.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import emu_size_table  # noqa: E402
import locate_file  # noqa: E402
import parse_dmmcfg as P  # noqa: E402

B = 0x108000
BUILD, NAME = "fx30_601", "outsz2560_fx30_v1"
IMG = locate_file.locate(BUILD, "cpapp-b.bin").read_bytes()
SHA = hashlib.sha256(IMG).hexdigest()
# (the tbh's address, its bound, the base the cases load from)
READERS = {"fx30_601": (0x480A36, 0xC, 0x155D3BC), "a7iv_602": (0x44566A, 0xC, 0x143C734)}


def case_load(build, case):
    """Decode the reader's tbh switch from the file: the address it jumps to for `case`, and the base and offset that case loads."""
    sw, bound, base = READERS[build]
    img = IMG if build == BUILD else locate_file.locate(build, "cpapp-b.bin").read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    pre = list(md.disasm(img[sw - 4 - B:sw + 4 - B], sw - 4))          # cmp r0, #bound (16-bit); bhi (16-bit); tbh
    assert [i.mnemonic for i in pre] == ["cmp", "bhi", "tbh"] and pre[0].op_str.endswith("#%#x" % bound), pre
    entries = struct.unpack_from("<%dH" % (bound + 1), img, sw + 4 - B)
    target = sw + 4 + 2 * entries[case]
    ins = list(md.disasm(img[target - B:target + 12 - B], target))[:3]
    if not ([i.mnemonic for i in ins][:2] == ["movw", "movt"] and ins[2].mnemonic in ("ldr", "ldr.w")):
        return target, None, None                       # a case that loads no entry (case 0 is the error report on the A7 IV and FX30)
    lo, hi = int(ins[0].op_str.split("#")[1], 0), int(ins[1].op_str.split("#")[1], 0)
    off = int(ins[2].op_str.split("#")[1].rstrip("]"), 0)
    assert (hi << 16 | lo) == base, (build, hex(hi << 16 | lo))
    return target, base, off


def raw_buffer_check(stage_rows=3976):
    """The movie raw write buffer (memory id 0x43e) against the open-gate first stage: does the stock unit hold it?

    The camera core's raw port set-up (A7 IV 0x247898 = FX30 0x24e6d8, match_thumb exact) refuses a frame whose
    ((lines - 1) * (step + 1) + 1) * line_bytes exceeds the unit; for the 1-byte type 6 its caller (A7 IV 0x6cef98 = FX30 0x715432) halves
    the lines and doubles the line bytes, so the need is rows x pitch. The pitch is the two first-stage halves' frame widths (record +0x20):
    the A7 IV's 2 x 3520 = 7040 gives its unit exactly (7040 x 3958 = 27,864,320, F673, camera-checked by requests 19 to 22); the FX30's
    halves are 2 x 3008 = 6016. Written to evidence/fx30/dmm/raw_write_buffer_fx30_601.json."""
    import emu_dmm_server as E
    E.use_build(BUILD)
    cfg = P.Config(P.find_file(BUILD), BUILD)
    units = cfg.units_by_key[0x57F]
    assert cfg.id_rows[0x43E]["keys"] == [0x57F] and {u["size"] for u in units} == {24676096} and len(units) == 4
    halves = {h: struct.unpack_from("<H", IMG, a - B + 0x20)[0] for h, a in (("L", 0xC79440), ("R", 0xC79FF8))}
    rows_stock = struct.unpack_from("<H", IMG, 0xC79440 - B + 0x0E)[0]
    a7 = locate_file.locate("a7iv_602", "cpapp-b.bin").read_bytes()
    a7_halves = [struct.unpack_from("<H", a7, a - B + 0x20)[0] for a in (0xBF7638, 0xBF81F0)]
    a7_rows = struct.unpack_from("<H", a7, 0xBF7638 - B + 0x0E)[0]
    assert sum(a7_halves) * a7_rows == 27864320, "the A7 IV's pitch rule does not give its unit"
    pitch, unit = halves["L"] + halves["R"], 24676096
    assert (pitch, rows_stock) == (6016, 3356)
    need, need_stock = pitch * stage_rows, pitch * rows_stock
    s = E.Server(cfg.data, cfg)
    assert s.init() == 0 and not s.fatal
    opens = [s.open(0x43E) for _ in range(6)]
    groups = {}
    for u in units:
        g = u["group"]
        groups.setdefault(hex(g["gid"]), {"parent": hex(g["parent"]), "parent_size": min(cfg.parent_sizes(g["parent"])), "limits": cfg.limits_text(g),
                                          "units": [[hex(x["key"]), x["size"]] for x in g["units"]], "layout_bytes": cfg.group_fit(g)[0],
                                          "path": cfg.path(g["parent"])})
    res = {"about": "FX30 6.01 movie raw write buffer (memory id 0x43e) against the open-gate first stage. Generated by build/build_ram_words_fx30.py "
                    "(raw_buffer_check). Verdict: no change is needed.",
           "memory_id": "0x43e", "key": "0x57f", "unit_size": unit, "units_in_config": len(units), "groups": groups,
           "pitch": {"value": pitch, "rule": "sum of the two first-stage halves' frame widths (record +0x20): FX30 3008 + 3008; the A7 IV's 3520 + 3520 = 7040 "
                                             "gives its unit exactly (7040 x 3958)", "a7iv_602_halves": a7_halves, "a7iv_602_rows": a7_rows},
           "check": "rows x pitch <= unit (raw port set-up 0x24e6d8 = A7 IV 0x247898; type 6 halving in 0x715432 = A7 IV 0x6cef98)",
           "stock_stage": {"rows": rows_stock, "bytes": need_stock, "spare": unit - need_stock},
           "open_gate_stage": {"rows": stage_rows, "bytes": need, "spare": unit - need, "fits": need <= unit},
           "largest_rows_that_fit": unit // pitch,
           "allocator_stock_opens_of_0x43e": [{"result": o["result"], "extents": o["extents"]} for o in opens],
           "margin_against_the_pitch_rule": {"largest_pitch_for_the_open_gate_stage": unit // stage_rows,
                                             "note": "any pitch up to this many bytes per row fits; 6016 is 190 below it"}}
    assert need <= unit
    ev = ROOT / "evidence/fx30/dmm"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "raw_write_buffer_fx30_601.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"raw write buffer: unit {unit:,}; stage {stage_rows} x {pitch} = {need:,} fits ({unit - need:,} spare); largest {unit // pitch} rows; "
          f"stock {rows_stock} rows = {need_stock:,}")
    return res


def main():
    raw_buffer_check()
    t, rows, writes = emu_size_table.table(BUILD)
    t_a, rows_a, _ = emu_size_table.table("a7iv_602")
    assert t == 0x155D40C and rows == rows_a, "the FX30's table differs from the A7 IV's"
    assert rows[6] == (3840, 2160, 0x43E) and rows[7] == (3840, 2160, 0x2D9)
    site = t + 8 * 7
    tgt, base, off = case_load(BUILD, 3)
    tgt_a, base_a, off_a = case_load("a7iv_602", 3)
    assert base + off == site and base_a + off_a == 0x143C7BC == t_a + 8 * 7, "case 3 does not load the second 3840 x 2160 entry"
    others = {c: case_load(BUILD, c)[2] for c in range(13)}
    others_a = {c: case_load("a7iv_602", c)[2] for c in range(13)}
    assert all((others[c] is None) == (others_a[c] is None) for c in range(13)), "the two switches load in different cases"
    assert all(others[c] is None or base + others[c] - t == base_a + others_a[c] - t_a for c in range(13)), "the two switches pick different entries"
    # every MOVW/MOVT of the base in the image, and the offsets loaded next to them: one load of base + 0x88 (the reader's case 3)
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    lo16, hi16 = base & 0xFFFF, base >> 16
    pat_lo = struct.pack("<HH", 0xF240 | ((lo16 >> 12) & 0xF) | (((lo16 >> 11) & 1) << 10), (((lo16 >> 8) & 7) << 12) | (lo16 & 0xFF))
    loads88 = []
    o = 0
    while True:
        o = IMG.find(pat_lo[:2], o)
        if o < 0:
            break
        if o % 2 == 0 and IMG[o + 2:o + 4][1] & 0x80 == 0 and (struct.unpack_from("<H", IMG, o + 2)[0] & 0x70FF) == (pat_lo[2] | pat_lo[3] << 8) & 0x70FF:
            for i in list(md.disasm(IMG[o:o + 16], o + B))[1:3]:
                if i.mnemonic in ("ldr", "ldr.w") and i.op_str.endswith("#0x88]"):
                    loads88.append(hex(i.address))
        o += 2
    cfg = P.Config(P.find_file(BUILD), BUILD)
    out_units = sorted(u["size"] for k in cfg.id_rows[0x2D9]["keys"] for u in cfg.units_by_key[k])
    assert out_units == [13271040] * 9 and 3840 * 2560 * 5 // 4 <= out_units[0]
    ref = json.loads((ROOT / "modding/designs/outsz2560_v1.json").read_text(encoding="utf8"))
    sites = [{"ram_address": hex(site), "old": struct.pack("<HH", 3840, 2160).hex(), "new": struct.pack("<HH", 3840, 2560).hex(),
              "note": "size class 3, second entry: output width and height [A7 IV 0x143c7bc]"}]
    guards = [{"ram_address": hex(site - 8), "bytes": struct.pack("<HHI", 3840, 2160, 0x43E).hex(),
               "note": "the entry before: 3840, 2160, memory id 0x43e [A7 IV 0x143c7b4]"},
              {"ram_address": hex(site + 4), "bytes": struct.pack("<I", 0x2D9).hex(), "note": "this entry's memory id, 0x2d9 [A7 IV 0x143c7c0]"}]
    for mine, theirs in ((sites, ref["sites"]), (guards, ref["guards"])):
        assert [(x.get("old"), x.get("new"), x.get("bytes")) for x in mine] == [(x.get("old"), x.get("new"), x.get("bytes")) for x in theirs]
    res = {"design": NAME, "build": BUILD, "camera": "ILME-FX30 (FX30), firmware 6.01",
           "title": "Output size of the stock 4K size class: 3840x2160 to 3840x2560, in the coprocessor's movie size table (RAM) (FX30 6.01 port)",
           "kind": "ram_words", "artifact": "cpapp-b.bin, RAM only: these bytes are not in the file",
           "emulated_image_sha256": SHA,
           "generated_by": "build/build_ram_words_fx30.py", "ported_from": {"design": "outsz2560_v1", "build": "a7iv_602"},
           "status": "addresses from emulating and reading the FX30's own code; never read or written on an FX30. The same word change (outsz2560_v1) "
                     "works on the A7 IV (requests 26 to 29, F688, F698, F700); the FX3's outsz2560_fx3_v1 works on the FX3 (2026-11-24)",
           "table": f"movie size table {t:#x} (base {base:#x} + 0x50; 0x4644bc fills it; the reader's tbh 0x480a36, case 3, loads base + {off:#x} = {site:#x})",
           "summary": dict(ref["summary"], goes_with=["the FX30 sensor-side design (5976 x 3976 first stage)",
                                                      "no raw-write-buffer change: the FX30's stock id 0x43e unit already holds the 3976-row stage"]),
           "emulated": {"function": "0x4644bc", "bytes": 0x37E, "base": hex(base), "table": hex(t), "stores_into_block": len(writes),
                        "entries_equal_a7iv_602": True, "entries": [[w, h, hex(m)] for w, h, m in rows],
                        "reader": {"switch": hex(READERS[BUILD][0]), "size_class_field": "[r6 + 0x7c] (A7 IV [r6 + 0x74])", "case_3_code": hex(tgt),
                                   "case_3_loads": hex(base + off), "cases_0_to_12_entry_offsets": [None if others[c] is None else hex(base + others[c] - t) for c in range(13)],
                                   "a7iv_602_switch": hex(READERS["a7iv_602"][0]), "a7iv_602_case_3_loads": hex(base_a + off_a),
                                   "loads_of_base_plus_0x88_in_the_image": loads88},
                        "output_buffer_id_0x2d9_units": out_units},
           "sites": sites, "guards": guards,
           "precondition": "none of its own: the table is read when a movie request is set up; write it with the camera in stills, as on the A7 IV",
           "restore": "write the old word back, or cold boot (the set-up fills the table again at start-up)",
           "checked_against": ["build/emu_size_table.py fx30_601 (the FX30's set-up run alone; entries equal the A7 IV's)",
                               "the tbh switches of the FX30 (0x480a36) and A7 IV (0x44566a) readers, decoded from the files: cases 0 to 12 pick the same entries (case 0 loads none in either)",
                               "the FX30's DmmCfg.bin: id 0x2d9 = 9 x 13,271,040 bytes, as the A7 IV's"],
           "not_shown": ["anything on an FX30",
                         "the FX30's format code in 4K (2 on the A7 IV camera, request 25; at code 3 a 3840x2560 picture would need 14,745,600 bytes, "
                         "more than the 13,271,040-byte unit)",
                         "that the reader is the only one: the scan for MOVW/MOVT of the base lists every load of base + 0x88 (above)"]}
    dd = ROOT / "modding/designs"
    (dd / f"{NAME}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf8", newline="\n")
    (dd / f"{NAME}_pokes_ram.txt").write_text("".join(f"{x['ram_address']} {x['new']}\n" for x in sites), encoding="utf8", newline="\n")
    print(f"{NAME}: site {site:#x} {sites[0]['old']} -> {sites[0]['new']}; guards {[g['ram_address'] for g in guards]}; table {t:#x} = A7 IV's; "
          f"reader case 3 at {tgt:#x} loads {base + off:#x} (A7 IV {base_a + off_a:#x}); loads of base + 0x88: {loads88}")


if __name__ == "__main__":
    main()
