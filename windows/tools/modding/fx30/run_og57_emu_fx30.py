"""FX30 6.01: function-level emulation of the 5760x3840 encoder-side designs (2026-11-28, the FX30's 5.7K step), stock against changed, in the
FX30's own av-cam.bin and libmpr.so. The changes are applied in emulated memory only.

  ogfile57r300m1_fx30_v4 / _v3   (build/build_og57.py --build fx30_601 --rate300 --m1all [--meta]): 300 Mbps on the 100M settings, M = 1 (no B
                                 pictures) in every descriptor, the HEVC edit list at 0; v4 also makes the MP4 headers say 5760x3840

The checks are those build/run_og57_emu.py makes on the A7 IV's designs and build/run_og57_si_emu_fx2.py on the FX2's, with the FX30's functions
(build/run_ogfile_emu_fx30.py found them and points the A7 IV harness at them):
  av-cam.bin  the descriptor matcher, the clip-format matcher, the memory-class function, the start-block builder; the codec firmware's memory
              calculation (build/emu_vcd_chmem.py; the codec file is the A7 IV's byte for byte) against the FX30's own main-processor blocks
  libmpr.so   g_videoParamComb (the encoder request's raster), the MP4 writer's track config, stsd entry and PROF entry
The edit-list site is emulated by build/emu_elst_site_v3.py --build fx30_601; the MP4 size sites for every request by
build/emu_mp4_meta.py --build fx30_601 --both.

Run with the Python that has Unicorn:  C:\\Python313\\python.exe -B build/run_og57_emu_fx30.py     writes evidence/fx30/encoder/og57_emu_fx30.json
Nothing was run on a camera.
"""
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import emu_mp4_meta  # noqa: E402
import locate_file  # noqa: E402
import run_ogfile_emu_fx30 as F  # noqa: E402  (its FN table points the A7 IV harness at the FX30's functions)

V, D, BUILD = F.V, F.D, F.BUILD
W0, H0 = 3840, 2160
DEST = ROOT / "evidence/fx30/encoder/og57_emu_fx30.json"
M1 = {0xE: 0x97, 4: 0x9B}                            # the profile's MParam: HEVC +0x97, AVC +0x9b (build_og57.M1_MPARAM_FAM); descriptor PredMode +0x85


def apply(data, binary, name):
    out = bytearray(data)
    for off, nb in F.pokes(D / f"{name}_pokes_{binary}.txt"):
        out[off:off + len(nb)] = nb
    return bytes(out)


def runs_of(a, b):
    out = []
    for i in (i for i in range(len(a)) if a[i] != b[i]):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [{"offset": hex(x), "bytes": y - x + 1, "first": a[x:y + 1].hex(), "second": b[x:y + 1].hex()} for x, y in out]


def check(name, av, lm, size_of):
    dz = json.loads((D / f"{name}.json").read_text(encoding="utf8"))
    assert dz["build"] == BUILD
    W1, H1 = dz["raster"]
    big = f"{W1}x{H1}"
    res, checks = {"design": name, "format": dz["format"]}, {}
    # ---- libmpr: the encoder request's raster, and the MP4 track config / stsd / PROF of the four formats
    lmc = apply(lm, "libmpr", name)
    rows = sorted({int(re.search(r"row (\d+)", p["note"]).group(1)) for p in dz["patches"] if p["kind"] == "L1-comb"})
    others = [r for r in (4, 9, 12, 13) if r not in rows]
    comb = {r: {"stock": list(struct.unpack_from("<HH", lm, F.COMB + 0x18 * r + 4)), "changed": list(struct.unpack_from("<HH", lmc, F.COMB + 0x18 * r + 4))}
            for r in rows + others}
    checks["encoder request raster: rows %s 3840x2160 -> %s, rows %s unchanged" % (rows, big, others)] = (
        rows == [0, 2, 5, 7] and all(comb[r]["stock"] == [W0, H0] and comb[r]["changed"] == [W1, H1] for r in rows)
        and all(comb[r]["stock"] == comb[r]["changed"] for r in others))
    meta = any(p["kind"] == "L4-mp4size" for p in dz["patches"])
    want = [W1, H1] if meta else [W0, H0]
    libs = {"stock": emu_mp4_meta.Lib(lm, BUILD), "changed": emu_mp4_meta.Lib(lmc, BUILD)}
    mrows = []
    for cb in (0, 2, 5, 7):
        for rate_code in (0, 2):
            for rate_index in range(2, 0x36):
                row = {"comb": cb, "rate_code": rate_code, "rate_index": rate_index}
                for k, lib in libs.items():
                    r, cfg = lib.config(cb, rate_code, rate_index)
                    rs, sz = lib.stsd(cfg)
                    rp, pf = lib.prof(cfg)
                    row[k] = {"config": [struct.unpack_from("<H", cfg, 0x2A)[0], struct.unpack_from("<H", cfg, 0x28)[0]], "stsd": [rs, list(sz)], "prof": [rp, pf]}
                if row["stock"]["stsd"][0] == 0 and row["stock"]["prof"][0] == 0:
                    mrows.append(row)
    checks["MP4 track config, stsd and PROF of every request the stock writer accepts: %s with the stock profile id%s" % (
        "x".join(map(str, want)), "" if meta else " (no header sites: the headers keep 3840x2160)")] = bool(mrows) and all(
        r["changed"]["config"] == want and r["changed"]["stsd"] == [0, want] and r["changed"]["prof"][0] == 0
        and r["changed"]["prof"][1]["profile_id"] == r["stock"]["prof"][1]["profile_id"] for r in mrows)
    res["libmpr"] = {"comb_rows": {str(k): v for k, v in comb.items()}, "mp4_requests_checked": len(mrows)}
    # ---- av-cam: the matcher
    avc = apply(av, "avcam", name)
    s, c = F.AvCam(av, F.FN), F.AvCam(avc, F.FN)
    sel, good = [], True
    for p in dz["descriptors"]:
        k = p["descriptor"]
        d = s.desc(k)
        row = {"descriptor": k, "format": p["format"], "rate": p["rate"], "quality_class": p["quality_class"], "key": d["key"],
               "stock_3840x2160": s.select(d, W0, H0), f"stock_{big}": s.select(d, W1, H1), f"changed_{big}": c.select(d, W1, H1), "changed_3840x2160": c.select(d, W0, H0)}
        row["as_designed"] = row["stock_3840x2160"] == k and row[f"stock_{big}"] is None and row[f"changed_{big}"] == k and row["changed_3840x2160"] is None
        good &= row["as_designed"]
        sel.append(row)
    checks["matcher: each of the %d changed descriptors is found for %s, no longer for 3840x2160" % (len(sel), big)] = good and len(sel) == 29
    changed = {p["descriptor"] for p in dz["descriptors"]}
    untouched = []
    for k in range(F.NDESC):
        d = s.desc(k)
        if d["infr"] or k in changed or d["codec"] not in (4, 0xE, 0x18):
            continue
        if (d["w"], d["h"]) == (W0, H0) or d["w"] >= W1:
            untouched.append({"descriptor": k, "codec": hex(d["codec"]), "raster": [d["w"], d["h"]], "coding_rate_code": d["codfr"],
                              "stock": s.select(d, d["w"], d["h"]), "changed": c.select(d, d["w"], d["h"]), f"changed_{big}": c.select(d, W1, H1)})
    checks["matcher: every other 3840x2160 / 5760-wide AVC, HEVC, S-I request: the same answer; none finds a descriptor at %s" % big] = (
        bool(untouched) and all(u["stock"] == u["changed"] for u in untouched) and all(u[f"changed_{big}"] is None for u in untouched))
    res["encoder_selection"] = {"changed": sel, "untouched_checked": len(untouched), "untouched_examples": untouched[:6]}
    # ---- clip-format code
    clips = [{"raster": [w, h], "stock": s.clip(w, h), "changed": c.clip(w, h)} for w, h in ((W1, H1), (W0, H0), (8192, 4320), (1920, 1080))]
    res["clip_code"] = clips
    checks["clip-format code: %s 0 -> 23 (the 4K code), 3840x2160 23 kept, 8192x4320 3 -> 0 (its row rewritten), 1920x1080 kept" % big] = (
        [x["stock"] for x in clips] == [0, 23, 3, 26] and [x["changed"] for x in clips] == [23, 23, 0, 26])
    # ---- memory: which ids the memory function asks for, and the codec's own calculation against row 3
    table = [struct.unpack_from("<4I", avc, F.UNIT_TABLE + 0x10 * k) for k in range(5)]
    r3, r2 = table[3], table[2]
    firsts = {}
    for q in dz["descriptors"]:
        firsts.setdefault(s.desc(q["descriptor"])["codec"], q["descriptor"])
    mem_ids, ok_ids = {}, True
    for cd, k in sorted(firsts.items()):
        d = s.desc(k)
        mem_ids[hex(cd)] = {"descriptor": k, f"request_{big}": {"stock": s.unit_ids(d, W1, H1), "changed": c.unit_ids(d, W1, H1)},
                            "request_3840x2160": {"stock": s.unit_ids(d, W0, H0), "changed": c.unit_ids(d, W0, H0)}}
        ch = mem_ids[hex(cd)][f"request_{big}"]["changed"]
        ok_ids &= (ch["memory_ids_asked"][:4] == [hex(r3[0]), hex(r3[1]), hex(r3[3]), hex(r3[2])] and not ch["errors_logged"]
                   and mem_ids[hex(cd)]["request_3840x2160"]["changed"] == mem_ids[hex(cd)]["request_3840x2160"]["stock"])
    checks["memory function: a %s request asks row 3 (CD, LD, ES, multi = %s); 3840x2160 asks as stock" % (big, [hex(x) for x in (r3[0], r3[1], r3[3], r3[2])])] = ok_ids
    res["memory_ids_by_codec"] = mem_ids
    fw = V.Firmware()
    have = [size_of(i) for i in r3]
    mem = []
    for dd in V.descriptors(avc):
        if dd["index"] not in changed:
            continue
        need = fw.need(dd)
        t, why = V.unit_type(dd)
        mem.append({"descriptor": dd["index"], "raster": [dd["w"], dd["h"]], "use_core": dd["use_core"], "unit_type": t,
                    "need": {k: need[k] for k in ("cd", "ld", "multi")}, "firmware_asserts": need["asserts"],
                    "fits": need["cd"] <= have[0] and need["ld"] <= have[1] and need["multi"] <= have[2]})
    checks["codec memory: every changed descriptor (two cores, unit type 3) fits the FX30's blocks of row 3 %s, no firmware assert" % have] = bool(mem) and all(
        m["fits"] and m["unit_type"] == 3 and m["raster"] == [W1, H1] and m["use_core"] == 2 and not m["firmware_asserts"] for m in mem)
    res["codec_memory"] = {"row_3": {"ids": [hex(i) for i in r3], "bytes": have}, "largest_need": {k: max(m["need"][k] for m in mem) for k in ("cd", "ld", "multi")},
                           "in_the_stock_order_of_row_2_would_fit": all(m["need"]["cd"] <= size_of(r2[0]) and m["need"]["ld"] <= size_of(r2[1])
                                                                        and m["need"]["multi"] <= size_of(r2[2]) for m in mem), "rows": mem}
    # ---- no B pictures: PredMode in every changed descriptor and MParam in its profile are 1 (stock 3)
    prof = {}
    for base, n in F.PROFILES:
        for k in range(n):
            prof[struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0]] = base + k * 0x100
    m1 = []
    for p in dz["descriptors"]:
        d = s.desc(p["descriptor"])
        do, po = F.DESC + 0x90 * p["descriptor"], prof[d["key"]]
        m1.append({"descriptor": p["descriptor"], "pred_mode": [av[do + 0x85], avc[do + 0x85]], "m_param": [av[po + M1[d["codec"]]], avc[po + M1[d["codec"]]]]})
    checks["no B pictures: PredMode and MParam 3 -> 1 in all %d descriptors and their profiles" % len(m1)] = bool(m1) and all(
        x["pred_mode"] == [3, 1] and x["m_param"] == [3, 1] for x in m1)
    res["m1"] = m1
    # ---- the start-block builder
    starts, sgood = [], True
    for p in dz["descriptors"]:
        d = s.desc(p["descriptor"])
        o, ten = prof[d["key"]], d["bitl"] == 1
        a, seq_a = s.start_block(av[o:o + 0x100], d, W0, H0, ten)
        b, seq_b = c.start_block(avc[o:o + 0x100], d, W1, H1, ten)
        br = 32 if d["codec"] == 0xE else 16
        first = struct.unpack_from("<H", seq_b, 0xC)[0]
        sgood &= (a["returned"] == 1 and not a["errors_logged"] and b["returned"] == 1 and not b["errors_logged"] and b["crop_size"] == [W1, H1]
                  and first == (-(-H1 // br) // 2) * br)
        starts.append({"descriptor": p["descriptor"], "key": d["key"], "stock_3840x2160": a, f"changed_{big}": b, "rows_for_first_core_in_the_block": first,
                       "sequence_block_differs_at": runs_of(seq_a, seq_b)})
    checks["start-block builder: every changed profile accepted at %s (crop, rows for the first core = half the picture in coding-block rows)" % big] = sgood
    res["start_block"] = starts
    res["checks"] = checks
    return res


def main():
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    assert locate_file.locate(BUILD, "vcd_firmware_imola2.bin").read_bytes() == locate_file.locate("a7iv_602", "vcd_firmware_imola2.bin").read_bytes()
    cfg = V.parse_dmmcfg.Config(V.parse_dmmcfg.find_file(BUILD, "setting"), BUILD)

    def size_of(i):
        units = [u for kk in cfg.id_json(i).get("keys", []) for u in kk["units"]] if i else []
        return max(u["size_bytes"] for u in units) if units else None

    out = {"about": "FX30 6.01: function-level emulation of the 5760x3840 encoder-side designs, stock against changed, in the FX30's own av-cam.bin and "
                    "libmpr.so (build/run_og57_emu_fx30.py). The requests are built from the descriptors' own fields, not from a traced caller. Nothing "
                    "was run on a camera.", "designs": []}
    bad = []
    for name in ("ogfile57r300m1_fx30_v4", "ogfile57r300m1_fx30_v3"):
        r = check(name, av, lm, size_of)
        out["designs"].append(r)
        print("==", name)
        for k, v in r["checks"].items():
            print("   %s  %s" % ("PASS" if v else "FAIL", k))
            if not v:
                bad.append(f"{name}: {k}")
        print("   codec memory: largest need", r["codec_memory"]["largest_need"], "blocks", r["codec_memory"]["row_3"])
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("wrote", DEST)
    print("ALL CHECKS PASS (%d)" % sum(len(r["checks"]) for r in out["designs"]) if not bad else "FAILED: " + "; ".join(bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
