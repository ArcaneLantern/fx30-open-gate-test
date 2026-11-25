"""Build `avdec8k_fx30_v1`: in-camera playback of the FX30 kit's 3840 x 2560 clips, in the A7 IV's form (FX30 port, 2026-11-26).

  C:/Python313/python.exe -B build/build_avdec_fx30.py

The FX3's `avdec8k_fx3_v1` (build/build_avdec_fx3.py; built 2026-11-25, NOT run on any camera) on the FX30 6.01's av-cam.bin. The FX30 has the
FX3's decode form (modding/FX3_PORT.md "Other bodies"; confirmed here on the FX30's own file): its decode create-ch always takes row 0 of a
three-row size table, 4096 x 2160, with the 4K decode memory ids 0x47d / 0x47f, so a 3840 x 2560 clip is expected not to play ("Unable to
display"), as on the FX3. The decode functions are the FX3's, 0x1938 lower (allocation 0x21714c, create-ch 0x21738c, its row choice 0x2174b4;
the caller that makes the clip type 0x1af0 lower, 0x22869c; the allocator 0x22b8a4 = A7 IV 0x222bd0). The design is the FX3's at those places:

  av-cam.bin code (kernel text, file offset = address - 0xffffffc001000000), the decode-memory allocation 0x21714c:
    0x21717c  mov w2,  #0x47d  ->  mov w2,  #0x47c     the id asked for (first allocation)
    0x217188  mov w20, #0x47d  ->  mov w20, #0x47c     its copy for the failure log line
    0x2171f8  mov w2,  #0x47f  ->  mov w2,  #0x47e     the id asked for (second allocation)
    0x217204  mov w21, #0x47f  ->  mov w21, #0x47e     its copy for the failure log line
  av-cam.bin data, the decode size table 0xbf6570 (20-byte rows; read only by create-ch at 0x21751c):
    0xbf6570  row 0 width, height 4096 x 2160 -> 7690 x 4320; the rest of the row is the A7 IV's row 3 already

Every check of the FX3 builder is made again on the FX30's file: the instruction sequences (branch targets compared where they matter), the
caller's clip types (11 / 12 / 13 / 10, never 14), the row choice, the table and its one reader, the decode memory in the FX30's main-processor
DmmCfg (the A7 IV's sizes), and every other `mov wN, #0x47c..0x47f` (log or assert line numbers). The bytes written equal the FX3 design's.
Nothing is run on a camera.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

import avcam_fnport  # noqa: E402
import parse_dmmcfg as P

ROOT = Path(__file__).resolve().parent.parent
BUILD, REF, FX3 = "fx30_601", "a7iv_602", "fx3_702"
NAME = "avdec8k_fx30_v1"
KVA = 0xFFFFFFC001000000                  # av-cam.bin's link and run address (liro.ko loads it at physical 0x401000000, memrsv ...:ex)
AVCAM_PHYS = 0x401000000
D_DEC, D_CALL = -0x1938, -0x1AF0          # FX30 = FX3 + delta: the decode functions, and the caller / allocator
CODE_PAGE, DATA_PAGE = 0x217000, 0xBF6000
TABLE, ROW = 0xBF6570, 20
ALLOC, CREATE, CALLER, ALLOCATOR = 0x21714C, 0x21738C, 0x22869C, 0x22B8A4
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True


def avcam(build):
    return (ROOT / f"work/extracted/{build}/0700_part_image/dev/nflasha3/av-cam.bin").read_bytes()


def word(d, off):
    return struct.unpack_from("<I", d, off)[0]


def asm(d, off, n=1):
    """n instructions from file offset off, as 'mnemonic op_str' with branch targets as file offsets."""
    out = []
    for i in md.disasm(d[off:off + 4 * n], KVA + off):
        s = f"{i.mnemonic} {i.op_str}".strip()
        if i.mnemonic in ("bl", "b", "cbz", "cbnz", "tbz", "tbnz") or i.mnemonic.startswith("b."):
            t = i.operands[-1].imm & 0xFFFFFFFFFFFFFFFF
            s = s.replace("#0x%x" % t, "@%x" % (t - KVA))
        elif i.mnemonic == "adrp":
            s = s.replace("#0x%x" % (i.operands[-1].imm & 0xFFFFFFFFFFFFFFFF), "page@%x" % ((i.operands[-1].imm & 0xFFFFFFFFFFFFFFFF) - KVA))
        out.append(s)
    assert len(out) == n, "undecodable instruction near %#x" % off
    return out


def strip(seq):
    """Branch targets and ADRP pages left out (they differ between the builds)."""
    return [s.split(" @")[0].split(", @")[0].split(" page@")[0].split(", page@")[0].rstrip(",") for s in seq]


def movz_w(rd, imm):
    assert 0 <= imm < 0x10000 and 0 <= rd < 31
    return 0x52800000 | imm << 5 | rd


def adrp_refs(d, page_va, lo, hi, code_end):
    """(instruction offset, target) for every ADRP of `page_va` followed within 12 instructions by an ADD/LDR/STR on that register
    whose target lies in [lo, hi)."""
    out = []
    n = code_end // 4
    w = struct.unpack_from("<%dI" % n, d, 0)
    for i in range(n):
        x = w[i]
        if x & 0x9F000000 != 0x90000000:
            continue
        imm = ((x >> 5) & 0x7FFFF) << 2 | (x >> 29) & 3
        imm = (imm - (1 << 21) if imm & (1 << 20) else imm) << 12
        if ((KVA + 4 * i) & ~0xFFF) + imm != page_va:
            continue
        rd = x & 31
        for j in range(i + 1, min(i + 13, n)):
            y = w[j]
            if (y >> 5) & 31 != rd:
                continue
            if y & 0xFF800000 == 0x91000000:                        # add xd, xn, #imm
                t = page_va + ((y >> 10) & 0xFFF << (12 if y >> 22 & 1 else 0))
            elif y & 0x3B000000 == 0x39000000:                      # ldr/str (unsigned offset), any size
                t = page_va + ((y >> 10) & 0xFFF) * (1 << (y >> 30))
            else:
                continue
            if lo <= t - KVA < hi:
                out.append((4 * j, t - KVA))
    return out


def main():
    fx, a4, f3 = avcam(BUILD), avcam(REF), avcam(FX3)
    og = json.loads((ROOT / "modding/designs/ogfile2560_hs_s_fx30_v2.json").read_text(encoding="utf8"))
    sha = hashlib.sha256(fx).hexdigest()
    assert sha == og["artifact_sha256"]["av-cam.bin"], "not the av-cam.bin of the FX30 kit's other designs"
    fx3_design = json.loads((ROOT / "modding/designs/avdec8k_fx3_v1.json").read_text(encoding="utf8"))

    # 1. the allocation: the FX3's sequences (as build_avdec_fx3.py asserts them), here with the FX30's targets
    want = {0x218AA0: ["mov w8, #0x1070", "ldr x0, [x19, #0x10a0]", "add x4, x19, x8", "mov w1, #0x610000", "movk w1, #0x3c",
                       "mov w2, #0x47d", "mov w3, #-0x7f980000", "movk w3, #0xf3", "mov w20, #0x47d", "bl @22d394", "tbz w0, #0, @218ad4"],
            0x218B1C: ["mov w8, #0x1090", "ldr x0, [x19, #0x10a0]", "add x4, x19, x8", "mov w1, #0x610000", "movk w1, #0x3c",
                       "mov w2, #0x47f", "mov w3, #-0x7f980000", "movk w3, #0xf3", "mov w21, #0x47f", "bl @22d394", "tbnz w0, #0, @218b84"]}
    for at3, seq in want.items():
        assert asm(f3, at3, len(seq)) == seq, "the FX3 reference moved"
        at = at3 + D_DEC
        got = asm(fx, at, len(seq))
        assert strip(got) == strip(seq), "the FX30's decode allocation at %#x is not the FX3's" % at
        assert got[9] == "bl @%x" % ALLOCATOR and got[10].endswith("@%x" % (int(seq[10].rsplit("@", 1)[1], 16) + D_DEC)), got
    assert asm(fx, ALLOC, 4) == ["sub sp, sp, #0x30", "stp x21, x20, [sp, #0x10]", "stp x19, x30, [sp, #0x20]", "mov x19, x0"]
    assert asm(fx, 0x218AF8 + D_DEC, 1) == ["str w20, [sp, #8]"] and asm(fx, 0x218B6C + D_DEC, 1) == ["str w21, [sp, #8]"]   # the log copies' only use
    # the allocator called is the A7 IV's (relocated: its first 24 instructions with branch targets left out)
    assert strip(asm(fx, ALLOCATOR, 24)) == strip(asm(a4, 0x222BD0, 24)), "the allocators differ"
    # the whole allocation function and create-ch's first 120 instructions equal the FX3's (build/avcam_fnport.py's normaliser: branch
    # targets, ADRP pages and the low bits added to them aside)
    norm = lambda d, a, n: avcam_fnport.normalise(struct.unpack_from("<%dI" % n, d, a))
    assert norm(fx, ALLOC, 48) == norm(f3, ALLOC - D_DEC, 48)
    assert norm(fx, CREATE, 120) == norm(f3, CREATE - D_DEC, 120)

    # 2. the clip type: the FX30's caller makes 11, 12, 13 or 10, never 14 (the FX3's caller; the A7 IV's 14 is for its formats 0x26 / 0x27)
    fx3_caller = asm(f3, 0x22A198, 14)
    fx_caller = asm(fx, 0x22A198 + D_CALL, 14)
    assert strip(fx_caller) == strip(fx3_caller) and asm(fx, 0x22A1FC + D_CALL, 1) == ["stp w22, w23, [sp, #0xf4]"]
    assert [s for s in fx_caller if s.startswith("mov w22") or s.startswith("mov w8")] == ["mov w22, #0xb", "mov w8, #0xc", "mov w22, #0xa"]
    assert "cmp w8, #0x27" not in " ".join(fx_caller)

    # 3. the row: row 0 whenever the A7 IV takes row 0 or 3; the table read only by create-ch
    assert strip(asm(fx, 0x218DEC + D_DEC, 11)) == strip(["tbz w0, #0, @218e10", "ldrh w8, [x20, #0x48]", "ldrh w9, [x20, #0x4a]", "mul w8, w9, w8",
                                                         "cmp w8, #0x1fe, lsl #12", "mov w8, #1", "mov w22, #1", "cinc x23, x8, ls", "b @218e18",
                                                         "mov w22, wzr", "mov x23, xzr"])
    assert asm(fx, 0x218E50 + D_DEC, 2) == ["adrp x9, page@%x" % DATA_PAGE, "add x9, x9, #0x%x" % (TABLE - DATA_PAGE)]
    assert asm(fx, 0x218E64 + D_DEC, 1) == ["mov w8, #0x14"] and asm(fx, 0x218E78 + D_DEC, 1) == ["madd x8, x23, x8, x9"]
    fx_rows = [fx[TABLE + ROW * k:TABLE + ROW * (k + 1)] for k in range(3)]
    f3_rows = [f3[0xBF8E70 + ROW * k:0xBF8E70 + ROW * (k + 1)] for k in range(3)]
    a4_rows = [a4[0xBACEB0 + ROW * k:0xBACEB0 + ROW * (k + 1)] for k in range(4)]
    assert fx_rows == f3_rows == a4_rows[:3], "the FX30's three rows are not the FX3's / the A7 IV's rows 0 to 2"
    assert struct.unpack_from("<HH", fx_rows[0]) == (4096, 2160) and a4_rows[3][4:] == fx_rows[0][4:]
    refs = adrp_refs(fx, KVA + DATA_PAGE, TABLE, TABLE + 3 * ROW, 0xA00000)
    assert refs == [(0x218E54 + D_DEC, TABLE)], "the table is read elsewhere too: %s" % refs

    # 4. memory: the ids exist in the FX30's main-processor DmmCfg with the A7 IV's sizes (the FX3's too)
    mem = {}
    for b in (BUILD, REF):
        cfg = P.Config(P.find_file(b, "setting"), b)
        assert cfg.exact()
        row = {}
        for i in (0x47C, 0x47D, 0x47E, 0x47F):
            (k,) = cfg.id_rows[i]["keys"]
            row[i] = [(u["group"]["parent"], u["size"]) for u in cfg.units_by_key[k]]
        mem[b] = row
    assert mem[BUILD] == mem[REF], "the decode memory differs from the A7 IV's"
    assert mem[BUILD][0x47C] == [(0x6C4, 536182784)] and mem[BUILD][0x47E] == [(0x6DD, 135036928)]

    # 5. no other code asks for these ids: every other `mov wN, #0x47c..0x47f` is a line number of a log or assert call
    assert norm(fx, 0x2790D8, 16) == norm(f3, 0x27B228, 16), "the assert function is not the FX3's 0x27b228"
    others = []
    twins = {0x4C7E0: 0x4C7DC, 0x4C84C: 0x4C848, 0x4C8AC: 0x4C8A8}          # FX3 0x4cc4c / 0x4ccb8 / 0x4cd18 and their A7 IV twins
    for off in range(0, 0xA00000, 4):
        x = word(fx, off)
        if x & 0xFFE00000 == 0x52800000 and (x >> 5) & 0xFFFF in (0x47C, 0x47D, 0x47E, 0x47F) and not (ALLOC <= off < ALLOC + 0xC0):
            nxt = asm(fx, off + 4, 3)
            if x & 31 == 7:
                role = "line number of a log call (w7)"
            elif x & 31 == 2 and any(s == "bl @2790d8" for s in nxt[:2]):
                role = "line number of an assert call (w2; 0x2790d8 = FX3 0x27b228)"
            elif off in twins:
                assert strip(asm(a4, twins[off], 4)) == strip(asm(fx, off, 4)), "the A7 IV's twin of %#x differs" % off
                role = "w3 of a log call; the same at the A7 IV's %#x" % twins[off]
            else:
                raise AssertionError("an id-like immediate at %#x that is not a line number: %s" % (off, asm(fx, off, 1)))
            others.append((off, asm(fx, off, 1)[0], role))

    # the sites: the FX3 design's, moved
    code = [(0x218AB4, 2, 0x47D, 0x47C, "the id of the first decode-memory allocation (0x47d: 4K decode, 2 units of 152.3 MB in 0x6c4 -> 0x47c: 8K decode, the whole 536.2 MB of 0x6c4)"),
            (0x218AC0, 20, 0x47D, 0x47C, "its copy for the failure log line (str w20, [sp, #8] at %#x)" % (0x218AF8 + D_DEC)),
            (0x218B30, 2, 0x47F, 0x47E, "the id of the second allocation (0x47f: 2 units of 38.6 MB -> 0x47e: 135.0 MB in 0x6dd)"),
            (0x218B3C, 21, 0x47F, 0x47E, "its copy for the failure log line (str w21, [sp, #8] at %#x)" % (0x218B6C + D_DEC))]
    code_sites = []
    for off3, rd, old, new, what in code:
        off = off3 + D_DEC
        assert word(fx, off) == movz_w(rd, old) and off & ~0xFFF == CODE_PAGE
        code_sites.append({"file_off": hex(off), "kernel_address": hex(KVA + off), "old": struct.pack("<I", movz_w(rd, old)).hex(),
                           "new": struct.pack("<I", movz_w(rd, new)).hex(), "asm_old": "mov w%d, #%#x" % (rd, old),
                           "asm_new": "mov w%d, #%#x" % (rd, new), "what": what})
    for s, s3 in zip(code_sites, fx3_design["code_sites"]):
        assert (s["old"], s["new"]) == (s3["old"], s3["new"]) and int(s["file_off"], 16) == int(s3["file_off"], 16) + D_DEC
    data_sites = [{"file_off": hex(TABLE), "kernel_address": hex(KVA + TABLE), "old": struct.pack("<HH", 4096, 2160).hex(),
                   "new": struct.pack("<HH", 7690, 4320).hex(), "what": "decode size table row 0: width, height (the A7 IV's row 3)"}]
    assert [(d["old"], d["new"]) for d in data_sites] == [(d["old"], d["new"]) for d in fx3_design["data_sites"]]
    data_guards = [{"file_off": hex(TABLE + 4), "bytes": fx[TABLE + 4:TABLE + 16].hex(), "what": "row 0 after the size"},
                   {"file_off": hex(TABLE + 16), "bytes": fx[TABLE + 16:TABLE + 32].hex(), "what": "row 0 end, row 1"},
                   {"file_off": hex(TABLE + 32), "bytes": fx[TABLE + 32:TABLE + 48].hex(), "what": "row 1, row 2"},
                   {"file_off": hex(TABLE + 48), "bytes": fx[TABLE + 48:TABLE + 60].hex(), "what": "row 2"}]
    assert [g["bytes"] for g in data_guards] == [g["bytes"] for g in fx3_design["data_guards"]]
    # the kernel-text code page differs from the FX3's (other code around): its guard is this file's page
    out = {"design": NAME, "build": BUILD, "camera": "ILME-FX30 (FX30), firmware 6.01", "kind": "avcam_code_data",
           "title": "In-camera playback of 3840 x 2560 clips: the A7 IV's 8K decode channel (7690 x 4320, memory ids 0x47c / 0x47e)",
           "status": "built from the 6.01, 7.02 and 6.02 files; never read or written on an FX30. The FX3's same design (avdec8k_fx3_v1) is not run "
                     "either; the A7 IV plays its own 3840 x 2560 clips with this channel",
           "artifact": "av-cam.bin", "artifact_sha256": sha, "kernel_va_base": hex(KVA), "avcam_phys": hex(AVCAM_PHYS),
           "generated_by": "build/build_avdec_fx30.py",
           "ported_from": "avdec8k_fx3_v1 (FX3 7.02): the same bytes, the decode functions 0x1938 lower; A7 IV 6.02 allocation 0x20e3d8, row choice 0x20e788, table 0xbaceb0 row 3",
           "code_page": hex(CODE_PAGE), "code_sites": code_sites,
           "code_guard": "the whole code page 0x217000-0x217fff apart from the four sites must be as in the file, in the mapping and in the kernel's own view "
                         "(it holds the allocation 0x21714c, create-ch 0x21738c and its row choice 0x2174dc)",
           "data_page": hex(DATA_PAGE), "data_sites": data_sites, "data_guards": data_guards,
           "order": fx3_design["order"],
           "icache": {"processors": "4 x Cortex-A35 (update/0800_appli/setting/cxd90057.dtb of the FX30 6.01); kernel 4.9.337 (vermagic 4.9.337-scel+ SMP, as the FX3)",
                      "alias": "the code page is mapped at a user address with the kernel's offset from a 2 MB boundary (%#x), so a virtually indexed instruction "
                               "cache is invalidated at the same index as the kernel's fetches" % ((KVA + CODE_PAGE) & 0x1FFFFF),
                      "refuse": "an instruction cache that CTR_EL0 says is neither PIPT nor VIPT"},
           "checked": {"fx30_type_never_14": "the FX30 caller %#x makes types 11 / 12 / 13 / 10 (the FX3's 0x22a198); the A7 IV's 0x21f9c4 adds 14 for formats 0x26 / 0x27" % (0x22A198 + D_CALL),
                       "rows_equal": "FX30 rows 0-2 = FX3 rows 0-2 = A7 IV rows 0-2; A7 IV row 3 = row 0 with 7690 x 4320",
                       "table_readers": ["%#x (create-ch)" % (0x218E54 + D_DEC)],
                       "allocator": "FX30 0x22b8a4 = A7 IV 0x222bd0 (24 instructions, branch targets aside); arguments w1 0x61003c, w3 0x806800f3 the same",
                       "dmm": {hex(k): [[hex(p), s] for p, s in v] for k, v in mem[BUILD].items()},
                       "other_id_immediates": [[hex(o), a, r] for o, a, r in others],
                       "same_bytes_as_fx3_design": True},
           "restore": "readcheck.c level 30 (put back), or a cold boot: av-cam.bin is loaded again from flash",
           "not_shown": ["anything on an FX30 (or on an FX3: the FX3's same step is not run either)", "that the FX30 then plays 3840 x 2560 clips (the A7 IV does)",
                         "that 0x47e's group can be had during playback (region 0x6dd; see the FX3 notes)",
                         "the A7 IV's other limits (its 5.7K clips do not play in camera)"]}
    dst = ROOT / "modding" / "designs" / f"{NAME}.json"
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("av-cam.bin", sha[:16], "| code sites", [s["file_off"] for s in code_sites], "| row", data_sites[0]["file_off"])
    print("other id immediates (not changed):")
    for o, a, r in others:
        print("   %#x %s: %s" % (o, a, r))
    print("table readers %s" % refs)
    print("wrote", dst)


if __name__ == "__main__":
    sys.exit(main())
