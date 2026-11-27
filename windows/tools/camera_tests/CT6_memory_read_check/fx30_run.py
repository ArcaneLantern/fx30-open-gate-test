"""FX30 (ILME-FX30) firmware 6.01: run one of the two READ-ONLY helper libraries, or one write step, and save what it reports.

  python fx30_run.py check --dry-run | --selftest
  python fx30_run.py dump  --dry-run | --selftest
  python fx30_run.py check --go --firmware-shown 6.01
  python fx30_run.py dump  --go --firmware-shown 6.01 [--clear-result SHA256]
  python fx30_run.py <write step> --go --writes-memory --firmware-shown 6.01      (fx30_apply.py runs these)

  check   identity of the camera's software and what every site of the open-gate designs holds now: READY / NOT READY
          (the screen step's 30 words and the five stored records are reported as well, not counted)
  dump    the same, plus kernel and memory facts, the coprocessor's logs and some of its tables (sensor registers, stored
          records with the window they program, the window the SENSOR is programmed for and whether the two agree, the resize module,
          the display: panel type, 3:2 ratio, frame tables, de-squeeze ratios)

Both read-only libraries only read. Each creates one file, its result, on the camera's RAM disk; this script fetches it. The
library is written to the camera's service partition, loaded once, and deleted again in the same session.

The FX30 counterpart of fx3_run.py (FX30 port, 2026-11-26): this camera's libraries, pins and result reader. The FX30's main-processor
software is the FX3's moved; its image processor's sensor tables have the A7 IV's layout (modding/FX30_PORT.md).

Kit v2 (2026-11-26, after the first camera runs): the sensor design is ogsq_fx30_v2, which also writes the sensor's own window registers (the
register matrix's column 1). v1 left them stock, so the sensor sent 3348 rows while the tables said 3968: picture in the top 2160 of 2560 rows,
black below, blue cast (three cameras). The dump now reads the sensor's registers and says so when they and the stored record disagree.
"""
import argparse
import json
import platform
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "helper"))
sys.path.insert(0, str(HERE / "helper_fx30"))
import ct1_common as c  # noqa: E402
import ct6_level1_run as R  # noqa: E402

FIRMWARE, MODEL, BUILD = "6.01", "ILME-FX30", "fx30_601"
S3 = HERE / "helper_fx30"                      # this kit's folder (the name S3 is kept from s3_run.py)
PINS = {"check": ("libJit_fx30_check.so", "6ebb1d807abee22521a20e9f199f61cfe90eca84cf7592cbcb462ee2c20b2582"),      # fx30read_v2 (2026-11-26)
        "dump": ("libJit_fx30_dump.so", "94ae0c8b3ca3d6ac5897e8e88fd6d4eecd4cf323fac88e16f9c64f512e470c0a")}
LEVELS = {"check": 101, "dump": 102}              # numbers outside the A7 IV runner's own levels: none of its level-specific code runs
# THE WRITE STEPS. Each is one library built from the A7 IV helper's write code with this camera's tables (helper_fx30/build_fx30_write.sh).
# They change the running camera's memory until a cold boot. They are run through fx30_apply.py, never by a launcher of the read-only kit.
WRITE_STEPS = {
    "L5": ("libJit_fx30_L5.so", "dc077b471d6b2949b84bad495f28f4e44241a1704ac1726f60f4a05b09657e1a",
           "apply the sensor-side design ogsq_fx30_v2 (the 4K window 5952x3968 from row 94 in modes 0x820/0x880/0x890/0x8c0/0x8d0: the sensor's "
           "seven window registers in the register matrix, 6 table spans, the two picture records and the five stored records, NTSC or PAL as "
           "the camera holds them)"),
    "L6": ("libJit_fx30_L6.so", "2cf0e6c9a8a1cfc5bd530a6f20391cb82d4018e4ece86d4d71435f2bf604e9dd", "put back the sensor-side design ogsq_fx30_v2"),
    # Variant B of the sensor step, for an A/B test: ogsq_fx30_v2b = v2 with the two values a tester reported clean colour with (repo issue 1):
    # first phase-detect row = window row + 51 = 145 (v2: 121, on the phase-detect blocks' 48-row grid) and read-out length 2020 (v2: 2014).
    # Same sensor registers, same picture records. B5 instead of L5; B6 puts it back.
    "B5": ("libJit_fx30_B5.so", "a4879a2b8735b39836fb19b32ccc96d4c37561f957417f02a37f158f467c30a3",
           "apply the sensor-side design, VARIANT B (ogsq_fx30_v2b: as ogsq_fx30_v2, but first phase-detect row 145 and read-out length 2020)"),
    "B6": ("libJit_fx30_B6.so", "17d6a817fd99ebffd808bc1f91114e502f7f24605f6614d93e19244a6270daac", "put back the sensor-side design, variant B (ogsq_fx30_v2b)"),
    "L16": ("libJit_fx30_L16.so", "001deba3f0acd3bbb1c82576d97a984fb92f5c402e2663af08c42849cdae73d2", "apply the output size outsz2560_fx30_v1 (one word)"),
    "L17": ("libJit_fx30_L17.so", "837f42a801a44280cdc22db1654eb084584cdf2888830ca98c9e723a8d9c517a", "put back the output size outsz2560_fx30_v1"),
    # L19: the FX3 kit's encoder side with the MP4 header heights (ogfile2560_hs_s_fx30_v2: tkhd, stsd and Sony's PROF say 3840x2560). L20 puts
    # back either version. N19 = the same without the two heights (apply --no-meta); its put back is L20 too.
    "L19": ("libJit_fx30_L19.so", "e52ea484b835096c9e834e8b4ca103e7d2648466598c3ece67932fff973d481c", "apply the encoder-side design ogfile2560_hs_s_fx30_v2 (101 + 4 sites, and the MP4 headers say 3840x2560: 2 more)"),
    "L20": ("libJit_fx30_L20.so", "f5449f4d0a677ea6becee658c62cdd52711a093aa73895d4467f76686d6750ce", "put back the encoder-side design ogfile2560_hs_s_fx30_v2 (or v1)"),
    "N19": ("libJit_fx30_N19.so", "1b76af6812efd5151eb290acb19dbeb677af05e096faa50815c6bd5b0e18d9f1", "apply the encoder-side design ogfile2560_hs_s_fx30_v1 (101 + 4 sites; the MP4 headers keep 3840x2160)"),
    # The rear-screen step (optional): the same level 16/17 code with the screen words. No C step: the FX30's own De-Squeeze Display is kept.
    "S16": ("libJit_fx30_S16.so", "853887dbb06d1fddd177930203786060595efac0fd74e7e15cda9466a51de328", "apply the screen words lcd32dsq_fx30_v1 (3:2 picture on the rear screen, the focus-frame rectangles, and De-Squeeze Display ratios for a 3:2 picture: 30 words)"),
    "S17": ("libJit_fx30_S17.so", "f3d8fcba1ac6096dc1e8f81282f39cb185928b24b04b532cc589fc4f336e713a", "put back the screen words lcd32dsq_fx30_v1"),
    # The playback step (optional; NOT RUN ON ANY CAMERA, the FX3's own was not run either): in-camera playback of 3840x2560 clips with the A7 IV's
    # decode channel (avdec8k_fx30_v1: four code words and one table word of av-cam.bin, readcheck.c levels 29 / 30, the FX3 kit's step moved).
    "P29": ("libJit_fx30_P29.so", "11717457fb0a22c4a410b3167862310f144b7eb12a290dffca2c2803e33b7aad", "apply the playback decoder avdec8k_fx30_v1 (the A7 IV's 7690x4320 decode channel and its memory: 4 code words and 1 table word of av-cam.bin)"),
    "P30": ("libJit_fx30_P30.so", "811589289151f5c0a816bb10144b55aebd6416e3c7dd428e79eaad95817f0d31", "put back the playback decoder avdec8k_fx30_v1"),
    # The external-flash step (session HS1, 2026-11-27; NOT RUN ON A CAMERA): design fx30flash_v2 (modding/FX30_FLASH_ENABLE.md), its own helper
    # helper_fx30/fx30flash.c (build_fx30_flash.sh). In the main application's memory: two pointer slots of the shutter-type rules (the ZV-E1's
    # 'invalid' path instead of 'electronic'), the 12 flash menu flags of class LAX, and three key codes of libObj.so's heap copy of the shoe
    # table. F18 only reads (READY / APPLIED / NOT READY); it runs through the write path because it reads the process's memory the same way.
    "F18": ("libJit_fx30_F18.so", "c2f366016e744a4645d61ed2047ef2b5a7ba3932d9df485e6ef909be2a267f7e",
            "READ-ONLY check of the external-flash step fx30flash_v2 (the rule slots, the menu flags, libObj.so's shoe table; nothing is written)"),
    "F19": ("libJit_fx30_F19.so", "8bca805ffcc9ff5f0d0d1917a80313a8add4419d93e319f1c9cdb9ef3aae4c7c",
            "apply the external-flash step fx30flash_v2 (3 shoe-table words, 12 menu flags, 2 rule slots in the main application's memory)"),
    "F20": ("libJit_fx30_F20.so", "edc587cdb3d6d49e9225aa26abd92889d4591576a846238d93ad152fdac81db0", "put back the external-flash step fx30flash_v2"),
}
PINS.update({k: v[:2] for k, v in WRITE_STEPS.items()})
LEVELS.update({k: {"L": 200, "S": 300, "N": 500, "P": 600, "B": 700, "F": 800}[k[0]] + int(k[1:]) for k in WRITE_STEPS})
WHICH = "check"
DESIGN_MODES = ("0x820", "0x880", "0x890", "0x8c0", "0x8d0")
# Libraries this kit published before and no longer runs (kit v1, 2026-11-26). With PINS they are the files a run may delete from the camera's
# service partition when an earlier session left one behind (R.KNOWN_LIBS, as in fx3_run.py: a cut-off session leaves its library on that
# partition, which is flash and survives a cold boot, and every later run then stopped at "a file is already there").
EARLIER_LIBS = {
    "047b4401842b8066cb49f3821a70d05ffc03e24bfac96e4575a80570bac9cbad": "kit v1's L5 (ogsq_fx30_v1)",
    "7fa24bf0656168b143e0d60586b1ece69c41cf1574c94735fe543d3fcb0f086e": "kit v1's L6 (put back of ogsq_fx30_v1)",
    "a7d488117048de5070d8f291fa87750a2f576ad659e90d401e8cb95b96a6260a": "kit v1's read-only check (fx30read_v1)",
    "ff2c52a88b26305b1deb42c792c29f71b3d9af5b942edefe817d285d6a61774e": "kit v1's read-only dump (fx30read_v1)",
}
EXTRA_LIBS = {}                                   # --remove-library: one more file, named by its SHA-256 on the command line


def known_libs():
    out = {sha: "this kit's %s library (%s)" % ("read-only " + k if k in ("check", "dump") else "step " + k, name) for k, (name, sha) in PINS.items()}
    out.update(EARLIER_LIBS)
    out.update(EXTRA_LIBS)
    return out
# Lines the helpers print with "!!" that are not faults (first camera runs, 2026-11-25/26): a /proc file longer than the helper's copy limit,
# and the entries of /proc/driver/pcie that are directories (read() gives -21, EISDIR). They are kept in the report as notes.
HARMLESS = (re.compile(r"^!! truncated at \d+ bytes$"), re.compile(r"^!! read failed -21$"))


def split_problems(lines):
    """(problem lines, harmless notes) among the lines that start with "!!"."""
    marked = [ln for ln in lines if ln.startswith("!!")]
    notes = [ln for ln in marked if any(h.match(ln.strip()) for h in HARMLESS)]
    return [ln for ln in marked if ln not in notes], notes


def write_result(data):
    """The facts of a write step's result (the A7 IV helper's report format)."""
    import hashlib
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    pick = lambda start: next((ln for ln in lines if ln.startswith(start)), None)
    verdict = pick("== level 18 verdict: ")              # F18, the flash step's read-only check: READY, APPLIED or NOT READY
    outcome = (verdict[len("== level 18 verdict: "):].split(":")[0] if verdict else
               "UNDO INCOMPLETE" if pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE") else "DONE" if pick("DONE: ") else "NOTHING TO DO" if pick("NOTHING TO DO") else
               "NOT DONE (everything put back)" if pick("NOT DONE: ") else "NOTHING WRITTEN" if any("nothing is written" in ln for ln in lines) else "UNKNOWN")
    problems, notes = split_problems(lines)
    variant = pick("the stored records are the ")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": lines[0].startswith("readcheck 1 level %s" % WHICH[1:]),
            "euid": "see the result", "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(problems),
            "complete": any(ln.startswith("== done") for ln in lines[-3:]),
            "s3": {"step": WHICH, "what": WRITE_STEPS[WHICH][2], "outcome": outcome, "ok": outcome in ("DONE", "NOTHING TO DO", "READY", "APPLIED"),
                   "outcome_line": verdict or pick("DONE: ") or pick("NOTHING TO DO") or pick("NOT DONE: ") or pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"),
                   "flash_lines": [ln for ln in lines if ln.startswith(("InfraHotshoe instance", "table ", "  shoe entry", "instance bytes"))] if WHICH[0] == "F" else [],
                   "timing_variant": variant, "problem_lines": problems, "notes": notes}}


def reference():
    return json.loads((S3 / "fx30_reference.json").read_text(encoding="utf8"))


def expected():
    return json.loads((S3 / "fx30_expected.json").read_text(encoding="utf8"))


# ------------------------------------------------------------ reading a result

def check_result(data):
    """The facts of a result file. Keys the A7 IV runner prints, plus this helper's own under "s3"."""
    if WHICH in WRITE_STEPS:
        return write_result(data)
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    count = lambda pat: sum(1 for ln in lines if re.search(pat, ln))
    verdict = next((ln for ln in lines if ln.startswith("VERDICT ")), "no verdict line")
    pages = {}
    for ln in lines:
        if ln.startswith("cppage "):
            _, name, addr, hx = ln.split(" ", 3)
            pages[int(addr, 16)] = (name, bytes.fromhex(hx.strip()))
    sites, other = [], {}
    for ln in lines:
        m = re.match(r"site (\S+) (0x[0-9a-f]+) len (\d+)(?: bytes (?:differing from stock )?(\S+))?  (STOCK|TARGET-B|TARGET|OTHER.*|NOT READ)$", ln)
        if m:
            sites.append({"name": m.group(1), "address": m.group(2), "length": int(m.group(3)), "shown": m.group(4), "state": m.group(5)})
        m = re.match(r"other (\S+) ([0-9a-f]+)$", ln)
        if m:
            other[m.group(1)] = bytes.fromhex(m.group(2))
    s3 = {"header": head, "verdict": verdict, "ready": verdict.startswith("VERDICT READY"),
          "identity_same": count(r"SAME as the 6\.01 update$"), "identity_differs": count(r"DIFFERS from the 6\.01 update$"),
          "coprocessor_sites": sites, "libmpr_sites": [ln for ln in lines if ln.startswith("lm ")],
          "avcam_stock": count(r"^av .*  STOCK$"), "avcam_target": count(r"^av .*  TARGET$"), "avcam_other": count(r"^av .*  OTHER$"),
          "avcam_guards": [ln for ln in lines if ln.startswith("guard ")], "pages": len(pages)}
    s3["problem_lines"], s3["notes"] = split_problems(lines)
    s3["stored_records"] = stored_record_states(sites, other)
    # which variant of the sensor design the two table spans that differ (LC, read-out) hold
    two = [s["state"] for s in sites if s["name"] in expected().get("variant_b_sites", []) and not s["name"].startswith("stored_record_")]
    s3["sensor_variant"] = (None if not two else "stock" if set(two) == {"STOCK"} else "A (ogsq_fx30_v2)" if set(two) == {"TARGET"} else
                            "B (ogsq_fx30_v2b)" if set(two) == {"TARGET-B"} else "mixed or unknown: %s" % two)
    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)
    s3["kernel_command_line"], s3["kernel_version"] = (cmd.group(1).strip() if cmd else None), (ver.group(1).strip() if ver else None)
    if pages:
        s3["decoded"] = decode_pages(pages)
        sv = s3["decoded"].get("sensor_vs_record", {})
        if sv.get("agree") is False:                 # found by the PC, not printed by the helper: the fault of kit v1
            s3["problem_lines"].append("!! (found by this script) the sensor is programmed for %d rows from row %d, the stored records say %d rows from row %d: "
                                       "the picture will not fill the frame" % (sv["sensor"][0], sv["sensor"][1], sv["record"][0], sv["record"][1]))
    import hashlib
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "header_ok": head.startswith("fx30read ") and "ILME-FX30 6.01" in head, "euid": "not read",
            "sections": [ln for ln in lines if ln.startswith("== ")], "problems": len(s3["problem_lines"]), "complete": "== done" in lines[-3:],
            "s3": s3, "_pages": pages}


def record_state(mode, rec):
    """What one stored record holds at the design's offsets: stock or applied, and in which timing variant (NTSC 60 Hz / PAL 50 Hz)."""
    ref = reference()
    for label, designs in (("", ref["stored_records_design"]), (", variant B", ref.get("stored_records_design_b"))):
        if not designs:
            continue
        sr = designs[mode]
        offs = [int(x, 16) for x in sr["offsets_that_differ"]]
        got = bytes(rec[k] for k in offs)
        for v in ("ntsc", "pal"):
            for what, key in (("stock", "stock"), ("applied" + label, "design")):
                if got == bytes(bytes.fromhex(sr[v][key])[k] for k in offs):
                    return f"{what} ({v.upper()})"
    return "other"


def stored_record_states(sites, other):
    out = {}
    for s in sites:
        if not s["name"].startswith("stored_record_"):
            continue
        mode = s["name"][len("stored_record_"):]
        if s["state"] in ("STOCK", "TARGET", "TARGET-B"):
            out[mode] = {"STOCK": "stock (NTSC)", "TARGET": "applied (NTSC)", "TARGET-B": "applied, variant B (NTSC)"}[s["state"]]
        elif s["name"] in other:
            out[mode] = record_state(mode, other[s["name"]])
        else:
            out[mode] = "not read"
    return out


def decode_pages(pages):
    """What the dump's coprocessor pages say, set against the firmware file's tables."""
    ref, out = reference(), {}

    def mem(addr, n):
        b = bytearray()
        while n:
            page = pages.get(addr & ~0xFFF)
            if page is None:
                return None
            take = min(n, 4096 - (addr & 0xFFF))
            b += page[1][addr & 0xFFF:(addr & 0xFFF) + take]
            addr, n = addr + take, n - take
        return bytes(b)

    # The register matrix (154 rows: the address of a register's value in the shadow, 14 column bytes) and the sensor register shadow. The
    # camera's own matrix is used where the dump holds it (the open gate changes seven bytes of column 1), else the file's. Columns 1, 2, 8
    # and 9 (the four 6K-class windows) differ only in the window registers 6/7, 8/9, 14, 16 and 25.
    rows = [(m[0], bytes.fromhex(m[1])) for m in ref["matrix"]]
    regs = {m[2]: m[0] for m in ref["matrix"]}             # register number -> address of its value in the shadow
    ncol = ref["matrix_columns"]
    sw = ref["sensor_window"]
    m0, rb = int(ref["matrix_address"], 16), ref["matrix_row_bytes"]
    got = mem(m0, rb * len(rows))
    live = rows
    if got is not None:
        want = b"".join(struct.pack("<I", a) + cols for a, cols in rows)
        diff = {m0 + o: (want[o], got[o]) for o in range(len(want)) if want[o] != got[o]}
        cells = {int(a, 16): tuple(sw["registers"][r]) for r, a in sw["cells"].items()}
        out["matrix_equals_file"] = not diff
        out["matrix_state"] = ("as the firmware file" if not diff else
                               "the firmware file's with the open gate's seven sensor-window bytes (%s)" % sw["sensor_design"] if diff == cells else
                               "%d bytes differ from the firmware file and from the open gate" % len(diff))
        out["matrix_bytes_differing_from_file"] = [[hex(a), w, g] for a, (w, g) in sorted(diff.items())][:64]
        if all(got[rb * i:rb * i + 4] == struct.pack("<I", a) for i, (a, _) in enumerate(rows)):
            live = [(a, got[rb * i + 4:rb * i + rb]) for i, (a, _) in enumerate(rows)]
    shadow = [(a, mem(a, 1)) for a, _ in rows]
    best = None
    if all(v is not None for _, v in shadow):
        score = [sum(1 for (a, cols), (_, v) in zip(live, shadow) if cols[k] == v[0]) for k in range(ncol)]
        best = max(range(ncol), key=lambda k: score[k])
        users = [ref["mode_ids"][i] for i, col in enumerate(ref["column_map"]) if col == best]
        out["sensor_registers"] = {"rows": len(rows), "rows_equal_per_column": score, "closest_column": best, "modes_using_it": users,
                                   "columns_with_the_same_score": [k for k in range(ncol) if score[k] == score[best]],
                                   "rows_differing_from_it": [[i, hex(a), cols[best], v[0]] for i, ((a, cols), (_, v)) in enumerate(zip(live, shadow)) if cols[best] != v[0]][:64]}
        # the window the sensor is programmed for (what the camera last sent it)
        v = {r: mem(regs[r], 1)[0] for r in (1, 6, 7, 8, 9, 14, 16, 25)}
        start, pairs = v[6] | v[7] << 8, v[8] | v[9] << 8
        seven = {r: v[int(r)] for r in sw["registers"]}
        out["sensor_window"] = {"mode_register": v[1], "start_register": start, "line_pairs": pairs, "window_row": start - sw["row_bias"],
                                "rows": 2 * pairs - sw["margins"], "first_phase_detect_block": v[14], "phase_detect_rows": 2 * v[16], "readout_f2": v[25],
                                "state": ("stock 4K window" if all(seven[r] == sw["registers"][r][0] for r in seven) else
                                          "open gate window" if all(seven[r] == sw["registers"][r][1] for r in seven) else "another mode or window")}
    # the stored drive-parameter records against the emulated ones, and the window the five design modes' records program
    r0, size = int(ref["records_address"], 16), ref["record_size"]
    recs, window = {}, {}
    wo = {k: int(v, 16) for k, v in ref["window"]["record_offsets"].items()}
    for i, mid in enumerate(ref["mode_ids"]):
        b = mem(r0 + i * size, size)
        if b is None:
            continue
        emu = bytes.fromhex(ref["emulated_stock_records"][mid])
        diff = [o for o in range(size) if b[o] != emu[o]]
        recs[mid] = {"index": i, "all_zero": not any(b), "bytes_differing_from_emulation": len(diff), "offsets": [hex(o) for o in diff[:48]], "record": b.hex()}
        if mid in DESIGN_MODES:
            u = lambda k: struct.unpack_from("<H", b, wo[k])[0]
            window[mid] = {"state": record_state(mid, b), "window": [u("height"), u("row")], "pdaf_rows": u("pdaf_rows"), "first_pdaf_row": u("first_pdaf_row"),
                           "first_pdaf_block": u("first_block"),
                           "readout_line_periods": u("readout_length"), "sampling_ratio": [b[4], b[5], b[6], b[7]]}
    out["stored_records"] = recs
    out["design_mode_windows"] = window
    # Do the sensor and the stored records agree? Only where the sensor runs a mode of the open gate's column (a 4K movie mode).
    if "sensor_window" in out and len(window) == len(DESIGN_MODES):
        sn = out["sensor_window"]
        rec = {(w["window"][0], w["window"][1], w["pdaf_rows"], w["first_pdaf_block"]) for w in window.values()}
        if best != sw["column"]:
            out["sensor_vs_record"] = {"agree": None, "why": "the sensor is not in a 4K movie mode (its registers are closest to matrix column %d)" % best}
        elif len(rec) != 1:
            out["sensor_vs_record"] = {"agree": None, "why": "the five stored records differ from one another"}
        else:
            r, se = list(rec.pop()), [sn["rows"], sn["window_row"], sn["phase_detect_rows"], sn["first_phase_detect_block"]]
            out["sensor_vs_record"] = {"agree": r == se, "sensor": se, "record": r, "order": "rows, first row, phase-detect rows, first phase-detect block"}
    t = mem(int(ref["size_table_address"], 16), 128)
    if t is not None:
        out["size_table"] = [list(struct.unpack_from("<HHI", t, 8 * k)) for k in range(16)]
    # The resize module (the A7 IV's code: settings 0x1573a30, working structure 0x12ddef8; build/emu_rc_fit_fx30.py). The result block's
    # address is predicted only (0x1571ec4, the A7 IV's distance from the settings): the decoder searches the pages for known sizes.
    st = {}
    ws = mem(0x12DDEF8, 0xDC)
    if ws is not None:
        st["resize_work"] = {"pixel_aspect_q12": struct.unpack_from("<i", ws, 0x48)[0], "scale_h_q12": struct.unpack_from("<i", ws, 0x4C)[0],
                             "scale_v_q12": struct.unpack_from("<i", ws, 0x50)[0], "zoom_q16": struct.unpack_from("<i", ws, 0x24)[0], "head": ws[:0x60].hex()}
    blk = mem(0x1571EC4, 0x14)
    if blk is not None:
        w = struct.unpack_from("<10H", blk)
        st["predicted_result_block"] = {"address": "0x1571ec4 (not confirmed)", "words": list(w), "start": [round(w[2] + w[6] / 4096, 3), round(w[3] + w[7] / 4096, 3)],
                                        "size": [round(w[4] + w[8] / 4096, 3), round(w[5] + w[9] / 4096, 3)]}
    se = mem(0x1573A30, 0x20)
    if se is not None:
        st["resize_settings"] = se.hex()
    seen = {}
    pairs = {(5952, 3968), (5952, 3348), (5976, 3976), (5976, 3356), (4336, 2438), (4336, 2442), (3840, 2560), (3840, 2160), (2176, 2438), (2160, 2438), (1920, 1080)}
    for addr, (name, blob) in sorted(pages.items()):
        if name not in ("resizework", "resizestate"):
            continue
        for o in range(0, 4096 - 3, 2):
            p = struct.unpack_from("<HH", blob, o)
            if p in pairs:
                seen.setdefault("%dx%d" % p, []).append(hex(addr + o))
    st["where_sizes_occur"] = {k: v[:40] for k, v in sorted(seen.items())}
    if any(n in ("resizework", "resizestate") for n, _ in pages.values()):
        out["scaler_state"] = st
    # The display (modding/FX30_PORT_SCREEN.md; the FX3's code moved by +0x3890, its crop by +0x68bd6): panel-type bytes rear 0x16295d4
    # (4 or more counts as 1), second output 0x1629704 (2 or more counts as 2); a 16:9 picture is letterboxed (fit words 3) at width x n/d
    # (0x1e3048); while De-Squeeze Display is on, one ratio per factor; 2.0x also crops to its centre 4:3 unless the screen step turned it off.
    disp = {}
    types = mem(0x16295D4, 1), mem(0x1629704, 1)
    if None not in types:
        name = {1: "16:9", 2: "4:3", 3: "3:2"}
        rear, second = (1 if types[0][0] >= 4 else types[0][0]), min(types[1][0], 2)
        disp["panel_types"] = {"rear_0x16295d4": types[0][0], "rear_aspect": name.get(rear, "none"), "second_0x1629704": types[1][0], "second_aspect": name.get(second, "none")}
    fit, con = mem(0x1E2D38, 8), mem(0x1E3048, 8)
    if fit is not None and con is not None:
        n, d = con[2], con[4]
        known = {(9, 16): "16:9, stock", (2, 3): "3:2 (screen step applied)"}
        form = con[:2] == bytes.fromhex("4ff0") and con[3] == 0x0E and con[5] == 0x20 and con[6:] == bytes.fromhex("07e0")
        disp["fit_16x9_picture"] = {"on_4x3_panel": struct.unpack_from("<I", fit, 0)[0], "on_3x2_panel": struct.unpack_from("<I", fit, 4)[0]}
        disp["ratio_constants"] = {"address": "0x1e3048", "words": con.hex(), "height": "width x %d/%d" % (n, d),
                                   "state": known.get((n, d), "unknown") if form else "not the expected instructions"}
    rws = {}
    for t in (0xDE78DC, 0xDE7954, 0xDE79CC):
        b = mem(t, 0x78)
        if b is not None:
            rws[hex(t)] = {"row%d" % r: list(struct.unpack_from("<4H", b, 8 * (5 * r + 3))) for r in range(3)}
    if rws:
        disp["frame_rectangles_16x9_picture"] = rws
    dsq = {}
    for label, a_n, a_d in (("1.3x", 0x1E2F90, 0x1E2F94), ("1.5x", 0x1E2F98, 0x1E2F9C), ("1.6x", 0x1E2FA0, 0x1E2FA4), ("2.0x", 0x1E2F38, 0x1E2F3C)):
        wn, wd = mem(a_n, 4), mem(a_d, 2)
        if wn is not None and wd is not None:
            good = wn[:2] == bytes.fromhex("4ff0") and wn[3] == 0x0A and wd[1] == 0x25
            dsq[label] = "%d/%d" % (wn[2], wd[0]) if good else "not the expected instructions"
    if dsq:
        stock = {"1.3x": "45/104", "1.5x": "3/8", "1.6x": "15/44", "2.0x": "3/8"}
        new = {"1.3x": "20/39", "1.5x": "4/9", "1.6x": "40/99", "2.0x": "1/3"}
        disp["desqueeze_ratios_16x9_picture"] = dict(dsq, state="stock" if dsq == stock else "3:2 picture (screen step applied)" if dsq == new else "mixed or unknown")
    cr = mem(0x663B0C, 2), mem(0x663B3E, 2)
    if None not in cr:
        imm = {c_[0] if c_[1] == 0x28 else None for c_ in cr}
        disp["crop_2x"] = "on (stock: the centre 4:3 is shown)" if imm == {4} else "off (screen step: the whole frame)" if imm == {5} else "not the expected instructions"
    sw = ref.get("screen_words", [])
    if sw and all(mem(int(w["address"], 16), 4) is not None for w in sw):
        got = [mem(int(w["address"], 16), 4).hex() for w in sw]
        disp["screen_words"] = {"stock": sum(g == w["stock"] for g, w in zip(got, sw)), "new": sum(g == w["new"] for g, w in zip(got, sw)),
                                "other": sum(g not in (w["stock"], w["new"]) for g, w in zip(got, sw))}
    if disp:
        out["display"] = disp
    return out


# ------------------------------------------------------------ the A7 IV runner, pointed at this camera

def known_answer(session, camera):
    want = (S3 / "DeviceInfo.xml").read_bytes()
    there, data = R.read(camera, R.KNOWN_PATH)
    if not there or data != want:
        raise c.StopTest("DeviceInfo.xml is not the file of the 6.01 update (%s); nothing else is sent"
                         % ("the camera returned no file" if not there else "%d bytes, SHA-256 %s" % (len(data), c.sha256(data)[:16])))
    session.say("Known-answer read: DeviceInfo.xml equals the 6.01 file (the A7 IV, FX3 and others have the same file: the helper itself checks which camera this is)")


def run_helper(data):
    """What loading the uploaded bytes gives on a model FX30: the real AArch64 code in Unicorn if it is installed, else a canned text."""
    if WHICH in WRITE_STEPS:                        # the write libraries are emulated by helper_fx30/emu_fx30_write.py (and emu_fx30_flash.py); here only the session flow
        last = ("== level 18 verdict: READY: every guard is as in the file and every site holds the stock bytes (canned)" if WHICH == "F18"
                else "DONE: every site holds the target bytes (canned)")
        text = "readcheck 1 level %s\neuid 0\n== level %s\n%s\n== done, bytes written before this line: 0\n" % (WHICH[1:], WHICH[1:], last)
        return text.encode(), "canned"
    try:
        import emu_fx30
    except Exception:
        text = "fx30read fx30read_v2 %s for ILME-FX30 6.01; read-only\n== file /proc/version\nLinux (simulated)\n\n== end 18 bytes\n== summary\nVERDICT READY (canned)\n== done\n" % WHICH
        return text.encode(), "canned"
    r, text = emu_fx30.run(bytes(data))
    if r.bad:
        raise AssertionError("the emulated helper stopped: %s" % r.bad)
    return text.encode(), "emulated"


def make_sim(lib, files=None, fault=None):
    sim = _make_sim(lib, files, fault)
    if "/usr/share/pmbp/DeviceInfo.xml" not in (files or {}):
        sim.fs["/usr/share/pmbp/DeviceInfo.xml"] = (S3 / "DeviceInfo.xml").read_bytes()
    return sim


def use(which):
    """Point the runner's module state at one of this camera's libraries."""
    global WHICH
    WHICH = which
    name, sha = PINS[which]
    if not (S3 / name).is_file():
        raise SystemExit("%s is not in this kit%s. Nothing was sent." % (name, " (the write steps are not published yet)" if which in WRITE_STEPS else ""))
    R.LEVEL, R.DESIGN, R.LIB, R.LIB_SHA256 = LEVELS[which], "og4k_data_v1", S3 / name, sha
    R.check_result, R.known_answer, R.run_helper, R.make_sim = check_result, known_answer, run_helper, make_sim
    R.KNOWN_LIBS = known_libs()
    c.EXPECTED_FIRMWARE = FIRMWARE
    return R.library()


_make_sim = R.make_sim


def selftest(lib):
    done = []

    def check(cond, what):
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    W, D = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = R.simulate(lib, R.body_run)
    r = s.results.get("ct6", {})
    check(not stopped and not sim.unexpected and R.sent(s).count(W) == 1 and R.sent(s).count(D) == 1, "normal run: one write, one delete, nothing off the list")
    check(R.sent(s).index(D) < len(R.sent(s)) - 2 and R.sent(s)[-1] == "GET_FILE2", "normal run: the delete comes before the result is read")
    check(R.LIB_PATH.decode() not in sim.fs and sim.loads == 1, "normal run: the library was loaded once and is gone afterwards")
    f = r.get("result", {}).get("s3", {})
    if WHICH in WRITE_STEPS:
        check(f.get("ok") and r["result"]["header_ok"], "normal run: the step's result is read as DONE")
    else:
        check(f.get("ready") and not f.get("identity_differs"), "normal run: the %s helper reports a stock 6.01 camera as READY" % sim.how)
    if sim.how == "emulated":
        check(len(f["coprocessor_sites"]) == len(expected()["cp_sites"]) and f["avcam_stock"] == 101 and len(f["libmpr_sites"]) == expected()["lm_sites"] == 6,
              "normal run: every coprocessor site, 6 libmpr (4 rows, 2 MP4 header heights) and 101 av-cam sites are reported")
        check(f.get("stored_records") == {m: "stock (NTSC)" for m in DESIGN_MODES}, "normal run: the five stored records read as stock (NTSC)")
        if WHICH == "dump":
            d = f.get("decoded", {})
            check(d.get("matrix_equals_file") and len(d.get("stored_records", {})) == 31 and d.get("size_table"), "dump: the pages decode (matrix, 31 records, size table)")
            check(d.get("sensor_registers", {}).get("rows") == 154 and d.get("matrix_state") == "as the firmware file" and "sensor_window" in d
                  and d.get("sensor_vs_record", {}).get("agree") is None and not f["problem_lines"],
                  "dump: the 154 matrix rows and the sensor's window registers are read; a camera that is not in a 4K movie mode gives no verdict on them")
            check(all(v["window"] == [3348, 406] and v["state"] == "stock (NTSC)" for v in d.get("design_mode_windows", {}).values())
                  and len(d.get("design_mode_windows", {})) == 5, "dump: the five design modes' records program the stock 5952x3348 window from row 406")
            dp = d.get("display", {})
            check(dp.get("ratio_constants", {}).get("state") == "16:9, stock" and dp.get("fit_16x9_picture") == {"on_4x3_panel": 3, "on_3x2_panel": 3}
                  and all(v == {"row0": [0, 60, 640, 360], "row1": [0, 38, 640, 404], "row2": [0, 60, 640, 360]} for v in dp.get("frame_rectangles_16x9_picture", {"x": 0}).values())
                  and len(dp.get("frame_rectangles_16x9_picture", {})) == 3 and dp.get("desqueeze_ratios_16x9_picture", {}).get("state") == "stock"
                  and dp.get("crop_2x", "").startswith("on") and dp.get("screen_words") == {"stock": 30, "new": 0, "other": 0} and "panel_types" in dp,
                  "dump: the display pages decode (stock ratio 9/16, fit words, the three tables' rows, de-squeeze ratios and crop, the 30 screen words, panel types)")
    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): b"someone else's"})
    check(stopped and W not in R.sent(s) and D not in R.sent(s), "a foreign libJit.so on the camera: stops, nothing written, nothing deleted")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"old"})
    check(stopped and W not in R.sent(s), "a result already on the RAM disk: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp/jbusy": b""})
    check(stopped and W not in R.sent(s), "/tmp/jbusy present: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/usr/share/pmbp/DeviceInfo.xml": b"<other camera/>"})
    check(stopped and len(R.sent(s)) == 2, "another DeviceInfo.xml: stops after the known-answer read")
    s, sim, stopped = R.simulate(lib, R.body_run, fault="load")
    check(stopped and R.sent(s).count(D) == 1 and R.LIB_PATH.decode() not in sim.fs, "a camera that cannot load the library: it is still deleted")
    # a library an earlier session left on the service partition (it survives a cold boot): one of this kit's is deleted and the run goes on
    lp = R.LIB_PATH.decode()
    other = next((S3 / n).read_bytes() for k, (n, sha) in sorted(PINS.items()) if k != WHICH and (S3 / n).is_file())
    for left, what in ((other, "another step's library"), (lib, "this step's own library")):
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: left})
        names, lr = R.sent(s), s.results["ct6"].get("leftover_removed") or {}
        check(not stopped and not sim.unexpected and names.count(D) == 2 and names.count(W) == 1 and names.index(D) < names.index(W) and lp not in sim.fs
              and sim.loads == 1 and lr.get("gone") and lr.get("sha256") == c.sha256(left) and s.results["ct6"]["library_on_camera_after"] is False,
              "%s left on the camera: deleted first, then the normal run (one write, loaded once, gone afterwards)" % what)
    s, sim, stopped = R.simulate(lib, R.body_run, files={lp: other}, fault="sticky")
    check(stopped and W not in R.sent(s) and R.sent(s).count(D) == 1 and sim.fs.get(lp) == other, "a left library the camera will not delete: stops, nothing written")
    named = b"a file named with --remove-library"
    saved = dict(R.KNOWN_LIBS)
    try:
        R.KNOWN_LIBS[c.sha256(named)] = "the file named with --remove-library"
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: named})
        check(not stopped and R.sent(s).count(D) == 2 and R.sent(s).count(W) == 1 and lp not in sim.fs, "--remove-library with the file's SHA-256: deleted, then the normal run")
        s, sim, stopped = R.simulate(lib, R.body_run, files={lp: named + b"!"})
        check(stopped and W not in R.sent(s) and D not in R.sent(s) and c.sha256(named + b"!") in stopped, "--remove-library with another SHA-256: stops, nothing deleted, the file's SHA-256 is shown")
    finally:
        R.KNOWN_LIBS.clear()
        R.KNOWN_LIBS.update(saved)
    s, sim, stopped = R.simulate(lib, R.body_remove_only, files={lp: other})
    check(not stopped and R.sent(s).count(D) == 1 and W not in R.sent(s) and lp not in sim.fs and s.results["ct6"]["library_on_camera_after"] is False,
          "--remove-only: deletes another step's library of this kit too, writes nothing")
    s, sim, stopped = R.simulate(lib, R.body_remove_only, files={lp: b"someone else's"})
    check(stopped and D not in R.sent(s) and lp in sim.fs, "--remove-only: leaves a file that is none of this kit's")
    check(set(EARLIER_LIBS) <= set(R.KNOWN_LIBS) and all(sha in R.KNOWN_LIBS for _, sha in PINS.values()) and not set(EARLIER_LIBS) & {sha for _, sha in PINS.values()},
          "every library of this kit, current (%d) and of kit v1 (%d), is one a run may delete" % (len(PINS), len(EARLIER_LIBS)))
    check(len(R.refusals(lib)) == 15, "the guard refuses the 15 listed packets (changed library, other paths, backup, flash and debug writes ...)")
    check(split_problems(["!! truncated at 2048 bytes", "!! read failed -21", "!! read failed; nothing is written", "!! read failed -5", "ok"])
          == (["!! read failed; nothing is written", "!! read failed -5"], ["!! truncated at 2048 bytes", "!! read failed -21"]),
          "a long /proc file and the /proc/driver/pcie directories are notes; every other marked line stays a problem")
    return done


def report(session, facts, which):
    f = facts["s3"]
    if which in WRITE_STEPS:
        lines = ["FX30 6.01 step %s: %s" % (which, f["what"]), "OUTCOME: %s" % f["outcome"], str(f["outcome_line"])]
        if f.get("timing_variant"):
            lines.append(f["timing_variant"])
        lines += ["  " + ln for ln in f["problem_lines"]]
        lines += [ln if ln.startswith("  ") else "  " + ln for ln in f.get("flash_lines", []) if not ln.startswith("instance bytes")]
        if f.get("notes"):
            lines.append("notes (not faults: %d lines such as a directory under /proc/driver/pcie that cannot be read as a file)" % len(f["notes"]))
        session.save_bytes("fx30_report.txt", ("\n".join(lines) + "\n").encode())
        for ln in lines:
            session.say(ln)
        return
    lines = ["FX30 6.01 %s, %s" % (which, time.strftime("%Y-%m-%d %H:%M:%S")), f["header"], f["verdict"],
             "identity: %d same, %d differ" % (f["identity_same"], f["identity_differs"]),
             "kernel: %s" % f["kernel_version"], "command line: %s" % f["kernel_command_line"]]
    for s in f["coprocessor_sites"]:
        lines.append("  coprocessor %-22s %s len %-4d %s%s" % (s["name"], s["address"], s["length"], s["state"], "" if s["shown"] is None else "  (" + s["shown"] + ")"))
    lines.append("stored records of the five open-gate modes: " + ", ".join("%s %s" % kv for kv in f.get("stored_records", {}).items()))
    if f.get("sensor_variant"):
        lines.append("sensor design in memory: %s" % f["sensor_variant"])
    lines += ["  " + ln for ln in f["libmpr_sites"]] + ["  " + ln for ln in f["avcam_guards"]]
    lines.append("  av-cam.bin sites: %d stock, %d target, %d other" % (f["avcam_stock"], f["avcam_target"], f["avcam_other"]))
    lines += ["problem lines:"] + ["  " + ln for ln in f["problem_lines"]] if f["problem_lines"] else ["no problem lines"]
    if f.get("notes"):
        lines.append("notes (not faults): " + "; ".join("%d x %s" % (f["notes"].count(n), n.strip()) for n in sorted(set(f["notes"]))))
    d = f.get("decoded")
    if d:
        sr = d.get("sensor_registers")
        if sr:
            lines.append("sensor register shadow: closest matrix column %d (%d of %d rows equal; columns with the same score %s; modes %s)"
                         % (sr["closest_column"], sr["rows_equal_per_column"][sr["closest_column"]], sr["rows"], sr["columns_with_the_same_score"], ", ".join(sr["modes_using_it"])))
        lines.append("register matrix: %s" % d.get("matrix_state"))
        sn, sv = d.get("sensor_window"), d.get("sensor_vs_record", {})
        if sn:
            lines.append("SENSOR is programmed for: %d rows from row %d (%s), %d phase-detect rows from block %d, lead-in %d, sensor mode %d"
                         % (sn["rows"], sn["window_row"], sn["state"], sn["phase_detect_rows"], sn["first_phase_detect_block"], sn["readout_f2"], sn["mode_register"]))
            lines.append("  sensor and stored records: " + ("AGREE" if sv.get("agree") else "DO NOT AGREE (sensor %s, records %s: %s)" % (sv["sensor"], sv["record"], sv["order"])
                                                            if sv.get("agree") is False else "not compared: %s" % sv.get("why", "the records were not read")))
        zero = [m for m, v in d.get("stored_records", {}).items() if v["all_zero"]]
        same = [m for m, v in d.get("stored_records", {}).items() if not v["bytes_differing_from_emulation"]]
        lines.append("stored drive-parameter records: %d read, %d equal to the emulated ones, %d all zero" % (len(d.get("stored_records", {})), len(same), len(zero)))
        for m, v in d.get("design_mode_windows", {}).items():
            lines.append("  mode %s: %s; window %d rows from row %d, %d phase-detect rows from row %d, read-out %d line periods, sampling %s"
                         % (m, v["state"], v["window"][0], v["window"][1], v["pdaf_rows"], v["first_pdaf_row"], v["readout_line_periods"], v["sampling_ratio"]))
        if d.get("size_table"):
            lines.append("movie size table: " + "; ".join("%dx%d id %#x" % tuple(r) for r in d["size_table"]))
        ss = d.get("scaler_state")
        if ss:
            lines.append("resize module (the A7 IV's code; the result block's address is predicted, not confirmed):")
            rw = ss.get("resize_work")
            if rw:
                lines.append("  resize work: pixel aspect %d/4096 (3456 = 27/32: open gate), scales %d and %d /4096, zoom %d/65536" % (rw["pixel_aspect_q12"], rw["scale_h_q12"], rw["scale_v_q12"], rw["zoom_q16"]))
            bl = ss.get("predicted_result_block")
            if bl:
                lines.append("  predicted result block %s: words %s -> takes %s x %s from %s" % (bl["address"], bl["words"], bl["size"][0], bl["size"][1], bl["start"]))
            for k, v in ss.get("where_sizes_occur", {}).items():
                lines.append("  %s at %s%s" % (k, ", ".join(v[:10]), " ..." if len(v) > 10 else ""))
        dp = d.get("display")
        if dp:
            lines.append("display (what the screen step changes):")
            if "panel_types" in dp:
                t = dp["panel_types"]
                lines.append("  panel types: rear %d (%s), second output %d (%s)" % (t["rear_0x16295d4"], t["rear_aspect"], t["second_0x1629704"], t["second_aspect"]))
            if "ratio_constants" in dp:
                r, ft = dp["ratio_constants"], dp["fit_16x9_picture"]
                lines.append("  a 16:9 picture: height = %s (%s); fit word on a 4:3 panel %d, on a 3:2 panel %d" % (r["height"], r["state"], ft["on_4x3_panel"], ft["on_3x2_panel"]))
            if "desqueeze_ratios_16x9_picture" in dp:
                q = dp["desqueeze_ratios_16x9_picture"]
                lines.append("  De-Squeeze Display ratios: 1.3x %s, 1.5x %s, 1.6x %s, 2.0x %s (%s); 2.0x crop %s" % (q.get("1.3x"), q.get("1.5x"), q.get("1.6x"), q.get("2.0x"), q["state"], dp.get("crop_2x")))
            if "screen_words" in dp:
                lines.append("  screen step words: %(stock)d stock, %(new)d applied, %(other)d other" % dp["screen_words"])
            for t, rw in dp.get("frame_rectangles_16x9_picture", {}).items():
                lines.append("  frame table %s: row 0 %s, row 1 %s, row 2 %s" % (t, rw["row0"], rw["row1"], rw["row2"]))
    session.save_bytes("fx30_report.txt", ("\n".join(lines) + "\n").encode())
    for ln in lines[:8] + lines[-6:]:
        session.say(ln)


def last_saved_sha():
    """The SHA-256 of the result the newest saved session of this kit fetched, or None."""
    root = c.PRIVATE_ROOT
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
        try:
            return json.loads((folder / "manifest.json").read_text(encoding="utf8"))["results"]["ct6"]["result"]["sha256"]
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", choices=sorted(PINS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--remove-only", action="store_true")
    ap.add_argument("--clear-result", metavar="SHA256", help="first delete the result file of an earlier run from the RAM disk, only if its SHA-256 is this")
    ap.add_argument("--remove-library", metavar="SHA256", help="a libJit.so left on the camera's service partition that is none of this kit's: delete it first, "
                                                               "only if its SHA-256 is this (a library of this kit, v1 or v2, is deleted without being named)")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-memory", action="store_true", help="needed for a write step (L5, L6, B5, B6, L16, L17, L19, L20, N19, S16, S17, P29, P30): it changes the running camera's memory")
    a = ap.parse_args()
    if a.which in WRITE_STEPS and a.go and not (a.dry_run or a.selftest) and not a.writes_memory:
        raise SystemExit("%s is a write step: %s. It needs --writes-memory as well. Use fx30_apply.py. Nothing was sent." % (a.which, WRITE_STEPS[a.which][2]))
    if a.remove_library:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", a.remove_library):
            raise SystemExit("--remove-library takes the 64 hexadecimal digits of the file's SHA-256 (the stopped run prints them). Nothing was sent.")
        EXTRA_LIBS[a.remove_library.lower()] = "the file named with --remove-library"
    lib = use(a.which)
    if a.dry_run or a.selftest:
        if a.selftest:                              # --dry-run and --selftest win over --go (the launchers always pass --go): nothing is sent
            for line in selftest(lib):
                print("PASS  " + line)
            print("all checks passed; nothing was sent to any device")
        else:
            print("\n".join(R.dry_run_lines(lib)))
        return
    if not a.go or a.firmware_shown != FIRMWARE:
        raise SystemExit("A live run needs --go and --firmware-shown %s (the version the camera's menu shows). Nothing was sent." % FIRMWARE)
    R.refusals(lib)
    selftest(lib)                                   # the flow must pass on the simulated camera on the day, before the real one
    import ct1_stage2_service as service
    R.CLEAR_SHA = a.clear_result or last_saved_sha()
    body = R.body_remove_only if a.remove_only else R.body_run
    with c.Session("remove_only" if a.remove_only else "fx30_%s" % a.which, test="CT6") as session:
        session.results.update(firmware_shown_on_camera=a.firmware_shown, model=MODEL, which=a.which, library_sha256=PINS[a.which][1],
                               pc={"platform": platform.platform(), "python": sys.version.split()[0]})
        inner = service.connect(session)
        try:
            R.service_session(session, inner, lambda cam: body(session, cam, lib), lib)
            facts = session.results.get("ct6", {}).get("result")
            if facts and not a.remove_only:
                pages = facts.pop("_pages", {})
                for addr, (name, blob) in sorted(pages.items()):
                    session.save_bytes("cp_%s_%08x.bin" % (name, addr), blob)
                report(session, facts, a.which)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            print("Library sent: %s. On the camera now: %s." % (
                "yes" if out.get("library_sent") else "no",
                {False: "no (confirmed)", True: "YES", None: "not sent" if not out.get("library_sent") and not a.remove_only else "UNKNOWN"}[out.get("library_on_camera_after")]))
            if a.which in WRITE_STEPS:
                print("This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. On the A7S III the power switch did too: keep the camera on between steps.")
            else:
                print("Nothing on the camera was changed. Unplug and replug the USB cable before another run; a cold boot (battery out) clears the result file.")


if __name__ == "__main__":
    main()
