"""FX30 kit v2: does the PC's reading of a dump tell whether the SENSOR and the stored records agree? Offline; no camera. (2026-11-26)

  C:/Python313/python.exe -B test_fx30_dump_decode.py

Kit v1 changed every table and record of the open gate but not the sensor's own window registers, and nothing in its dump said so: the fault
was found on three cameras. This test holds the reading that now catches it (fx30_run.decode_pages / check_result), on
  - the built dump library run in Unicorn (emu_fx30.py's model) for: a stock camera in a stills mode, a stock camera in 4K movie, kit v2
    applied in 4K movie, and kit v1's state in 4K movie (tables and records for 3968 rows, sensor on the stock 3348);
  - the three real dumps of a tester's camera after kit v1 (evidence/fx30/camera/2026-11-25_pal: private, not published; skipped when the
    folder is not there), read with this kit's reference data.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import emu_fx30  # noqa: E402
import fx30_run as F  # noqa: E402

CAMERA = ROOT / "evidence/fx30/camera/2026-11-25_pal"
STOCK, OPEN, V1 = [3348, 406, 68, 9], [3968, 94, 82, 2], [3968, 96, 82, 2]     # rows, first row, phase-detect rows, first phase-detect block
done, failed = [], []


def check(cond, what):
    (done if cond else failed).append(what)
    print(("PASS  " if cond else "FAIL  ") + what)


def emulated(**kw):
    r, text = emu_fx30.run((HERE / "libJit_fx30_dump.so").read_bytes(), **kw)
    assert not r.bad, r.bad
    f = F.check_result(text.encode())["s3"]
    return f, f["decoded"]


def main():
    F.WHICH = "dump"
    f, d = emulated()
    check(d["sensor_vs_record"]["agree"] is None and not f["problem_lines"] and d["matrix_state"] == "as the firmware file",
          "stock camera in a stills mode: sensor and records are not compared, no problem line")
    f, d = emulated(movie=True)
    sn, sv = d["sensor_window"], d["sensor_vs_record"]
    check(sv == {"agree": True, "sensor": STOCK, "record": STOCK, "order": sv["order"]} and sn["state"] == "stock 4K window" and sn["mode_register"] == 15
          and sn["readout_f2"] == 41 and d["sensor_registers"]["closest_column"] == 1 and d["sensor_registers"]["columns_with_the_same_score"] == [1]
          and d["sensor_registers"]["rows_equal_per_column"][1] == 154 and not f["problem_lines"],
          "stock camera in 4K movie: the sensor reads 3348 rows from row 406 and agrees with the records; column 1 alone fits all 154 rows")
    f, d = emulated(applied=True, movie=True)
    sn, sv = d["sensor_window"], d["sensor_vs_record"]
    check(sv["agree"] is True and sv["sensor"] == OPEN == sv["record"] and sn["state"] == "open gate window" and sn["readout_f2"] == 48
          and "open gate's seven sensor-window bytes" in d["matrix_state"] and len(d["matrix_bytes_differing_from_file"]) == 7
          and d["sensor_registers"]["rows_equal_per_column"][1] == 154 and not f["problem_lines"]
          and all(w["state"] == "applied (NTSC)" for w in d["design_mode_windows"].values()),
          "kit v2 applied, 4K movie: the sensor reads 3968 rows from row 94 and agrees with the records; the matrix holds the seven new bytes")
    f, d = emulated(applied=True, movie=True, system="pal")
    check(d["sensor_vs_record"]["agree"] is True and all(w["state"] == "applied (PAL)" for w in d["design_mode_windows"].values()),
          "kit v2 applied on a PAL camera: the same")
    f, d = emulated(applied=True, movie=True, sensor="ogsq_fx30_v2b")
    w = d["design_mode_windows"]["0x8c0"]
    check(d["sensor_vs_record"]["agree"] is True and d["sensor_vs_record"]["sensor"] == OPEN and f["sensor_variant"] == "B (ogsq_fx30_v2b)"
          and all(v == "applied, variant B (NTSC)" for v in f["stored_records"].values()) and len(f["stored_records"]) == 5
          and all(x["state"] == "applied, variant B (NTSC)" for x in d["design_mode_windows"].values())
          and (w["first_pdaf_row"], w["readout_line_periods"]) == (145, 2020) and f["ready"] and not f["problem_lines"],
          "variant B applied, 4K movie: READY, read as variant B (first phase-detect row 145, read-out 2020), sensor and records agree")
    f, d = emulated(applied=True, movie=True, sensor="ogsq_fx30_v2b", system="pal")
    check(all(x["state"] == "applied, variant B (PAL)" for x in d["design_mode_windows"].values()) and f["sensor_variant"] == "B (ogsq_fx30_v2b)" and f["ready"],
          "variant B applied on a PAL camera: READY, read as variant B (PAL)")
    f, d = emulated(applied=True, movie=True)
    w = d["design_mode_windows"]["0x8c0"]
    check(f["sensor_variant"] == "A (ogsq_fx30_v2)" and (w["first_pdaf_row"], w["readout_line_periods"]) == (121, 2014), "the default design is read as variant A (121, 2014)")
    f, d = emulated()
    check(f["sensor_variant"] == "stock", "a stock camera is read as holding no sensor design")
    f, d = emulated(applied=True, movie=True, sensor="ogsq_fx30_v1")
    sv = d["sensor_vs_record"]
    check(sv["agree"] is False and sv["sensor"] == STOCK and sv["record"] == V1 and d["sensor_window"]["state"] == "stock 4K window"
          and any("the sensor is programmed for 3348 rows from row 406, the stored records say 3968 rows from row 96" in ln for ln in f["problem_lines"]),
          "kit v1's state, 4K movie: sensor 3348 rows, records 3968 rows -> DO NOT AGREE, and a problem line says so")
    # ---- the real camera
    if not CAMERA.is_dir():
        print("SKIP  the real dumps (evidence/fx30/camera/2026-11-25_pal is not here)")
    else:
        got = {}
        for folder in ("01_before_patch_stills", "02_after_patch_movie", "03_after_recording"):
            pages = {}
            for p in sorted((CAMERA / folder).glob("cp_*.bin")):
                name, addr = p.stem[3:].rsplit("_", 1)
                pages[int(addr, 16)] = (name, p.read_bytes())
            got[folder] = F.decode_pages(pages)
            text = (CAMERA / folder / "readcheck_result.txt").read_bytes()
            got[folder]["_facts"] = F.check_result(text)["s3"]
        d = got["01_before_patch_stills"]
        check(d["sensor_vs_record"]["agree"] is None and d["sensor_registers"]["closest_column"] == 5 and d["matrix_state"] == "as the firmware file",
              "real camera, before the patch (a stills mode, column 5): not compared")
        for folder in ("02_after_patch_movie", "03_after_recording"):
            d = got[folder]
            sv, f = d["sensor_vs_record"], d["_facts"]
            check(sv["agree"] is False and sv["sensor"] == STOCK and sv["record"] == V1 and d["sensor_window"]["state"] == "stock 4K window"
                  and d["matrix_state"] == "as the firmware file" and d["sensor_registers"]["closest_column"] == 1
                  and d["sensor_registers"]["columns_with_the_same_score"] == [1],
                  f"real camera, {folder}: the sensor was on the stock 3348-row window while the records said 3968 rows from row 96")
            check(len(f["problem_lines"]) == 1 and "the sensor is programmed for 3348 rows" in f["problem_lines"][0]
                  and sorted(set(n.strip() for n in f["notes"])) == ["!! truncated at 2048 bytes"],
                  f"real camera, {folder}: its result file now gives that one problem line; the two 'truncated' lines are notes")
    print("ALL PASS (%d checks)" % len(done) if not failed else "FAILED: %d of %d" % (len(failed), len(done) + len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
