"""FX30 6.01: function-level emulation of the encoder-side designs ogfile2560_hs_s_fx30_v1 and ogfile2560_hs_s_fx30_v2 (build/build_ogfile.py
--build fx30_601 [--meta]), stock against changed, in the FX30's own av-cam.bin and libmpr.so. The changes are applied in emulated memory only.
2026-11-26 (FX30 port, modding/FX30_PORT_ENCODER.md).

The A7 IV's run_ogfile_emu.py checks (as build/run_ogfile_emu_fx2.py), pointed at the FX30's functions, which are found first by code
(build/avcam_fnport.py's normaliser: branch targets, page offsets and literal offsets aside, everything else equal):
  descriptor matcher   0x224490  = A7 IV 0x21b780, whole body; reads the descriptors at 0x392758
  memory-class         0x21c40c  = A7 IV 0x2136c4, whole body; reads the unit-type table at 0x3926b8
  allocator (DMM open) 0x22b8a4  = A7 IV 0x222bd0;  log 0x27b418 = A7 IV 0x27278c;  log head 0x27b3d8 (the FX3's 0x27d528 shape)
  clip format          0x1956c0  = the FX3's 0x196b80 (the A7 IV's 0x190128 but one log line number); reads the clip table at 0x39061c
  start-block builder  0x220208  reached from the command fill 0x21df1c with the A7 IV's six instructions before the call (as on the FX3); its
                       own compile (the A7 IV's first 181 instructions, then other code): run as the FX30's own
  memcpy / memset      0x27b934 / 0x27b94c (call 0xd80 / 0x2f67c, as the A7 IV's and FX3's wrappers)
  codec memory         vcd_firmware_imola2.bin (the A7 IV's file byte for byte) against the FX30's main-processor blocks (frame rates 0x330290)
  libmpr.so            the encoder request's raster (g_videoParamComb 0x2cb138) and the MP4 track config 0x21fef0 for combs 0, 2, 5, 7
Run with the Python that has Unicorn:  C:\\Python313\\python.exe -B build/run_ogfile_emu_fx30.py      writes evidence/fx30/encoder/ogfile2560_emu_fx30.json
Nothing was run on a camera.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import avcam_fnport  # noqa: E402
import emu_mp4_meta  # noqa: E402
import emu_vcd_chmem as V  # noqa: E402
import locate_file  # noqa: E402
from run_ogfile_emu import AVB, AvCam, D, pokes  # noqa: E402

BUILD = "fx30_601"
DESC, NDESC, UNIT_TABLE, FPS_TABLE, CLIP = 0x392758, 689, 0x3926B8, 0x330290, 0x39061C
PROFILES = ((0x3AAAE8, 373), (0x3C20E8, 316))
COMB = 0x2CB138
FN = {"DESC": AVB + DESC, "MATCH": AVB + 0x224490, "CLIPFN": AVB + 0x1956C0, "UNITFN": AVB + 0x21C40C, "BUILDER": AVB + 0x220208,
      "DMM_OPEN": AVB + 0x22B8A4, "LOGF": AVB + 0x27B418, "LOGH": AVB + 0x27B3D8, "MEMSET": AVB + 0x27B94C, "MEMCPY": AVB + 0x27B934}
V.DESC, V.NDESC, V.UNIT_TABLE, V.FPS_TABLE = AVB + DESC, NDESC, AVB + UNIT_TABLE, AVB + FPS_TABLE


def bl_target(img, at):
    w = struct.unpack_from("<I", img, at)[0]
    assert w & 0xFC000000 == 0x94000000, hex(w)
    return at + 4 * ((w & 0x3FFFFFF) - ((w & 0x2000000) << 1))


def adrp_add(img, add_at):
    """The address the ADD at `add_at` forms with the nearest ADRP of its base register in the 8 instructions before (file offsets: av-cam is
    linked at a 4 KB-aligned base, so pages computed from file offsets are the file's)."""
    w2 = struct.unpack_from("<I", img, add_at)[0]
    assert w2 & 0xFFC00000 == 0x91000000, hex(w2)
    rn = (w2 >> 5) & 31
    for at in range(add_at - 4, add_at - 36, -4):
        w = struct.unpack_from("<I", img, at)[0]
        if w & 0x9F000000 == 0x90000000 and (w & 31) == rn:
            imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
            imm -= (1 << 21) if imm & (1 << 20) else 0
            return (at & ~0xFFF) + (imm << 12) + ((w2 >> 10) & 0xFFF)
    raise AssertionError("no ADRP before %#x" % add_at)


def find_functions(a7, f3, fx):
    """Assert where the FX30's functions are (see the docstring). Returns a dict for the report."""
    exact = avcam_fnport.port(BUILD, [0x21B780, 0x2136C4, 0x222BD0, 0x27278C], a7, fx)
    want = {0x21B780: 0x224490, 0x2136C4: 0x21C40C, 0x222BD0: 0x22B8A4, 0x27278C: 0x27B418}
    assert {k: v[0] for k, v in exact.items()} == want, exact
    # clip format: the FX3's 0x196b80 whole (normalised), which is the A7 IV's 0x190128 but one `mov w7, #line`
    n = avcam_fnport.a7iv_size(0x190128) // 4
    a = avcam_fnport.normalise(struct.unpack_from("<%dI" % n, a7, 0x190128))
    b3 = avcam_fnport.normalise(struct.unpack_from("<%dI" % n, f3, 0x196B80))
    b = avcam_fnport.normalise(struct.unpack_from("<%dI" % n, fx, 0x1956C0))
    diff = [k for k in range(n) if a[k] != b[k]]
    assert b == b3 and len(diff) == 1 and a[diff[0]] & 0xFFE0001F == b[diff[0]] & 0xFFE0001F == 0x52800007, diff
    # the tables they read
    assert adrp_add(fx, 0x1956D4) == CLIP and adrp_add(fx, 0x2245B8) == DESC and adrp_add(fx, 0x21C500) == UNIT_TABLE
    # the start-block builder: the call in the command fill, after the A7 IV's six instructions (as on the FX3)
    seq = struct.unpack_from("<6I", a7, 0x2151D4)
    sites = [x for x in range(0x210000, 0x230000, 4) if struct.unpack_from("<6I", fx, x) == seq]
    assert sites == [0x21DF1C], sites
    assert bl_target(fx, 0x21DF34) == 0x220208
    # log head: the FX3's 0x27d528 shape, 0x40 before the log function
    assert avcam_fnport.normalise(struct.unpack_from("<8I", f3, 0x27D528)) == avcam_fnport.normalise(struct.unpack_from("<8I", fx, 0x27B3D8))
    # memcpy / memset wrappers: the same shape, calling the same two routines as the A7 IV's
    for a7_at, fx_at in ((0x272CA8, 0x27B934), (0x272CC0, 0x27B94C)):
        wa, wf = struct.unpack_from("<6I", a7, a7_at), struct.unpack_from("<6I", fx, fx_at)
        assert wa[:2] == wf[:2] and wa[3:] == wf[3:] and bl_target(a7, a7_at + 8) == bl_target(fx, fx_at + 8), (hex(a7_at), hex(fx_at))
    # the frame-rate table the codec model reads: the A7 IV's 15 words
    assert fx[FPS_TABLE:FPS_TABLE + 60] == a7[0x3220A0:0x3220A0 + 60]
    return {"matcher": "0x224490 (= A7 IV 0x21b780)", "memory_ids": "0x21c40c (= A7 IV 0x2136c4)", "allocator": "0x22b8a4 (= A7 IV 0x222bd0)",
            "log": "0x27b418 (= A7 IV 0x27278c), head 0x27b3d8", "clip_format": "0x1956c0 (= FX3 0x196b80; A7 IV 0x190128 but one log line number)",
            "start_block": "0x220208 (called at 0x21df34; the FX30's own compile)", "memcpy_memset": "0x27b934 / 0x27b94c",
            "tables_read": {"descriptors": hex(DESC), "unit_types": hex(UNIT_TABLE), "clip": hex(CLIP), "frame_rates": hex(FPS_TABLE)}}


def avcam_checks(name, av):
    design = json.loads((D / f"{name}.json").read_text(encoding="utf8"))
    assert design["build"] == BUILD
    changed = bytearray(av)
    for off, new_bytes in pokes(D / f"{name}_pokes_avcam.txt"):
        changed[off:off + len(new_bytes)] = new_bytes
    changed = bytes(changed)
    s, c = AvCam(av, FN), AvCam(changed, FN)
    res = {"design": name, "format": design["format"]}
    sel, ok = [], True
    for p in design["descriptors"]:
        k = p["descriptor"]
        d = s.desc(k)
        row = {"descriptor": k, "format": p["format"], "rate": p["rate"], "quality_class": p["quality_class"], "key": d["key"],
               "stock_3840x2160": s.select(d, 3840, 2160), "stock_3840x2560": s.select(d, 3840, 2560),
               "changed_3840x2560": c.select(d, 3840, 2560), "changed_3840x2160": c.select(d, 3840, 2160)}
        row["as_designed"] = (row["stock_3840x2160"] == k and row["stock_3840x2560"] is None and row["changed_3840x2560"] == k and row["changed_3840x2160"] is None)
        ok &= row["as_designed"]
        sel.append(row)
    untouched = []
    changed_set = {p["descriptor"] for p in design["descriptors"]}
    codecs = {s.desc(k)["codec"] for k in changed_set}
    for k in range(NDESC):
        d = s.desc(k)
        if (d["w"], d["h"]) != (3840, 2160) or d["infr"] or k in changed_set:
            continue
        if d["codec"] in codecs and d["codfr"] in (0, 1, 2):          # the same formats at the other frame rates (29.97p, 50p, 59.94p ...)
            a, b = s.select(d, 3840, 2160), c.select(d, 3840, 2160)
            untouched.append({"descriptor": k, "codec": hex(d["codec"]), "coding_rate_code": d["codfr"], "stock": a, "changed": b,
                              "changed_3840x2560": c.select(d, 3840, 2560)})
    res["encoder_selection"] = {"every_changed_descriptor_as_designed": ok, "changed": sel, "untouched_checked": len(untouched),
                                "untouched_same_answer": all(u["stock"] == u["changed"] for u in untouched),
                                "untouched_refuse_2560": all(u["changed_3840x2560"] is None for u in untouched), "untouched_examples": untouched[:6]}
    res["clip_code"] = [{"raster": [w, h], "stock": s.clip(w, h), "changed": c.clip(w, h)} for w, h in ((3840, 2560), (3840, 2160), (8192, 4320), (1920, 1080))]
    firsts = {}
    for q in design["descriptors"]:
        firsts.setdefault(s.desc(q["descriptor"])["codec"], q["descriptor"])
    res["memory_class_by_codec"] = {hex(cd): {"descriptor": k,
                                              "request_3840x2560": {"stock": s.unit_ids(s.desc(k), 3840, 2560), "changed": c.unit_ids(s.desc(k), 3840, 2560)},
                                              "request_3840x2160": {"stock": s.unit_ids(s.desc(k), 3840, 2160), "changed": c.unit_ids(s.desc(k), 3840, 2160)}}
                                    for cd, k in sorted(firsts.items())}
    assert locate_file.locate(BUILD, "vcd_firmware_imola2.bin").read_bytes() == locate_file.locate("a7iv_602", "vcd_firmware_imola2.bin").read_bytes()
    fw = V.Firmware()
    table = [struct.unpack_from("<4I", changed, UNIT_TABLE + 0x10 * k) for k in range(4)]
    cfg = V.parse_dmmcfg.Config(V.parse_dmmcfg.find_file(BUILD, "setting"), BUILD)

    def size_of(i):
        units = [u for kk in cfg.id_json(i).get("keys", []) for u in kk["units"]] if i else []
        return max(u["size_bytes"] for u in units) if units else None

    have = [size_of(i) for i in table[3]]
    mem = []
    for dd in V.descriptors(changed):
        if dd["index"] not in changed_set:
            continue
        need = fw.need(dd)
        t, why = V.unit_type(dd)
        mem.append({"descriptor": dd["index"], "vsize": dd["h"], "unit_type": t, "need": {k: need[k] for k in ("cd", "ld", "multi")},
                    "fits": need["cd"] <= have[0] and need["ld"] <= have[1] and need["multi"] <= have[2], "firmware_asserts": need["asserts"]})
    res["codec_memory"] = {"blocks_of_row_3_after_the_change": {"ids": [hex(i) for i in table[3]], "bytes": have},
                           "every_changed_descriptor_fits": bool(mem) and all(m["fits"] and m["unit_type"] == 3 and m["vsize"] == 2560 and not m["firmware_asserts"] for m in mem),
                           "largest_need": {k: max(m["need"][k] for m in mem) for k in ("cd", "ld", "multi")}, "rows": mem}
    prof = {}
    for base, n in PROFILES:
        for k in range(n):
            prof[struct.unpack_from("<I", av, base + k * 0x100 + 0x20)[0]] = base + k * 0x100
    starts, good = [], True
    for p in design["descriptors"]:
        d = s.desc(p["descriptor"])
        o = prof[d["key"]]
        ten = d["bitl"] == 1
        try:
            a, seq_a = s.start_block(av[o:o + 0x100], d, 3840, 2160, ten)
            b, seq_b = c.start_block(changed[o:o + 0x100], d, 3840, 2560, ten)
        except RuntimeError as e:
            starts.append({"descriptor": p["descriptor"], "error": str(e)})
            good = False
            continue
        diff = [i for i in range(0x1C0) if seq_a[i] != seq_b[i]]
        runs = []
        for i in diff:
            if runs and i == runs[-1][1] + 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        starts.append({"descriptor": p["descriptor"], "key": d["key"], "stock_2160": a, "changed_2560": b,
                       "sequence_block_differs_at": [{"offset": hex(x), "bytes": y - x + 1, "stock": seq_a[x:y + 1].hex(), "changed": seq_b[x:y + 1].hex()} for x, y in runs]})
        good &= a["returned"] == 1 and not a["errors_logged"] and a["crop_size"] == [3840, 2160]
        good &= b["returned"] == 1 and not b["errors_logged"] and b["crop_size"] == [3840, 2560]
    res["start_block"] = {"every_changed_profile_accepted": good, "rows": starts}
    return res


def libmpr_checks(name, lm):
    design = json.loads((D / f"{name}.json").read_text(encoding="utf8"))
    changed = bytearray(lm)
    for off, new_bytes in pokes(D / f"{name}_pokes_libmpr.txt"):
        changed[off:off + len(new_bytes)] = new_bytes
    changed = bytes(changed)
    rows = {}
    for comb in (0, 2, 5, 7, 9, 12):
        rows[comb] = {"stock": list(struct.unpack_from("<HH", lm, COMB + 0x18 * comb + 4)), "changed": list(struct.unpack_from("<HH", changed, COMB + 0x18 * comb + 4))}
    mp4 = {}
    libs = {"stock": emu_mp4_meta.Lib(lm, BUILD), "changed": emu_mp4_meta.Lib(changed, BUILD)}
    for comb in (0, 2, 5, 7):
        for rate_code in (0, 2):
            got = {}
            for k, lib in libs.items():
                r, cfg = lib.config(comb, rate_code, 0x20)
                got[k] = [struct.unpack_from("<H", cfg, 0x2A)[0], struct.unpack_from("<H", cfg, 0x28)[0]]
            mp4[f"comb {comb} rate code {rate_code}"] = got
    want_h = 2560 if any(p["kind"] == "L4-mp4size" for p in design["patches"]) else 2160
    ok = (all(rows[c]["stock"] == [3840, 2160] and rows[c]["changed"] == [3840, 2560] for c in (0, 2, 5, 7))
          and all(rows[c]["stock"] == rows[c]["changed"] for c in (9, 12))
          and all(v["stock"] == [3840, 2160] and v["changed"] == [3840, want_h] for v in mp4.values()))
    return {"encoder_request_raster_by_comb": {str(k): v for k, v in rows.items()}, "mp4_track_config_by_comb": mp4,
            "mp4_height_expected": want_h, "as_designed": ok}


def main():
    a7 = locate_file.locate("a7iv_602", "av-cam.bin").read_bytes()
    f3 = locate_file.locate("fx3_702", "av-cam.bin").read_bytes()
    av = locate_file.locate(BUILD, "av-cam.bin").read_bytes()
    lm = locate_file.locate(BUILD, "libmpr.so").read_bytes()
    out = {"about": "FX30 6.01: function-level emulation of ogfile2560_hs_s_fx30_v1 and _v2, stock against changed, in the FX30's own av-cam.bin and libmpr.so "
                    "(build/run_ogfile_emu_fx30.py, the A7 IV's run_ogfile_emu.py checks pointed at the FX30's functions). The requests are built from the "
                    "descriptors' own fields, not from a traced caller. Nothing was run on a camera.",
           "functions": find_functions(a7, f3, av), "designs": []}
    for name in ("ogfile2560_hs_s_fx30_v1", "ogfile2560_hs_s_fx30_v2"):
        r = avcam_checks(name, av)
        r["libmpr"] = libmpr_checks(name, lm)
        out["designs"].append(r)
    dst = ROOT / "evidence/fx30/encoder/ogfile2560_emu_fx30.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    for r in out["designs"]:
        e = r["encoder_selection"]
        print("==", r["design"])
        print("   matcher: changed descriptors as designed:", e["every_changed_descriptor_as_designed"], "| untouched checked:", e["untouched_checked"],
              "same answer:", e["untouched_same_answer"], "refuse 2560:", e["untouched_refuse_2560"])
        for row in e["changed"]:
            if not row["as_designed"]:
                print("      NOT as designed:", row)
        print("   clip code:", r["clip_code"])
        print("   memory class:", json.dumps({k: {q: v[q] for q in ("request_3840x2560",)} for k, v in r["memory_class_by_codec"].items()}))
        m = r["codec_memory"]
        print("   codec memory: blocks", m["blocks_of_row_3_after_the_change"], "fits:", m["every_changed_descriptor_fits"], "largest need:", m["largest_need"])
        print("   start block: accepted:", r["start_block"]["every_changed_profile_accepted"], [x.get("error") for x in r["start_block"]["rows"] if "error" in x][:2])
        print("   libmpr:", "as designed:", r["libmpr"]["as_designed"], r["libmpr"]["mp4_track_config_by_comb"])
    print("wrote", dst)
    bad = []
    for r in out["designs"]:
        e, mc = r["encoder_selection"], r["memory_class_by_codec"]
        checks = {"matcher": e["every_changed_descriptor_as_designed"] and e["untouched_same_answer"] and e["untouched_refuse_2560"] and e["untouched_checked"] > 0,
                  "clip": [x["changed"] for x in r["clip_code"]] == [23, 23, 0, 26] and [x["stock"] for x in r["clip_code"]] == [0, 23, 3, 26],
                  "memory class": all(v["request_3840x2560"]["changed"]["memory_ids_asked"][:4] == ["0x486", "0x474", "0x47a", "0x477"]
                                      and v["request_3840x2160"]["changed"] == v["request_3840x2160"]["stock"] for v in mc.values()),
                  "codec memory": r["codec_memory"]["every_changed_descriptor_fits"], "start block": r["start_block"]["every_changed_profile_accepted"],
                  "libmpr": r["libmpr"]["as_designed"]}
        bad += [f"{r['design']}: {k}" for k, v in checks.items() if not v]
    print("ALL CHECKS PASS" if not bad else "FAILED: " + "; ".join(bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
