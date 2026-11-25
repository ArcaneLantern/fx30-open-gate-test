"""Cross-check the FX30 6.01 VDF calculators under qemu-arm (a second emulator besides Unicorn's build/emu_lcd_fx30.py).

  wsl python3 -I -B build/lcd_fx30_qemu.py [--work DIR] [--save]

The FX3 kit's build/lcd_fx3_qemu.py ported: the same ARM Linux guest (build/lcd_fx3_qemu.c, used as it is: it takes the leaf functions
as files), run in WSL with arm-linux-gnueabi-gcc and qemu-arm. The leaf functions are cut from cpapp-b.bin 6.01, stock and with
modding/designs/lcd32dsq_fx30_v1.json applied, and run for the cases of the Unicorn run (evidence/fx30/screen/lcd32dsq_fx30_v1_emu.json)
on the FX30's 1024 x 768 panel and the FX3's 800 x 600 and 720 x 480. Every rectangle must equal Unicorn's.
--save writes evidence/fx30/screen/lcd32dsq_fx30_v1_qemu.json.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "work/extracted/fx30_601/0700_part_image/dev/nflasha8/cpapp-b.bin"
SHA = "2877ba56332e9157bfea7610b2ac8561e6edfbea9c26ff8bafa0531f8fe3a247"
B = 0x108000
LEAVES = {"fit": (0x1E2CE8, 0x1E2D7C), "ratio": (0x1E3024, 0x1E3114), "dsq": (0x1E2F10, 0x1E3024)}      # FX3 7.02 leaves + 0x3890
PANELS = {"4:3 1024x768": (1024, 768, 0), "4:3": (800, 600, 0), "3:2": (720, 480, 1)}
EMU = ROOT / "evidence/fx30/screen/lcd32dsq_fx30_v1_emu.json"


def images():
    stock = IMAGE.read_bytes()
    assert hashlib.sha256(stock).hexdigest() == SHA
    design = json.loads((ROOT / "modding/designs/lcd32dsq_fx30_v1.json").read_text(encoding="utf8"))
    pat = bytearray(stock)
    for s in design["sites"]:
        a = int(s["ram_address"], 16)
        assert pat[a - B:a - B + 4] == bytes.fromhex(s["old"])
        pat[a - B:a - B + 4] = bytes.fromhex(s["new"])
    return stock, bytes(pat)


def cases():
    out = []
    for name, (w, h, pc) in PANELS.items():
        for asp in range(6):
            for p in (0, 1):
                out.append(("ratio", p, w, h, pc, asp, 0, name))
        for asp in (0, 1, 2, 5):
            for code in range(5):
                for p in (0, 1):
                    out.append(("dsq", p, w, h, pc, asp, code, name))
    return out


def run(work):
    stock, pat = images()
    leaf = lambda img, k: img[LEAVES[k][0] - B:LEAVES[k][1] - B]
    assert leaf(stock, "fit") == leaf(pat, "fit")
    for name, data in (("fit", leaf(stock, "fit")), ("ratio_stock", leaf(stock, "ratio")), ("ratio_patched", leaf(pat, "ratio")),
                       ("dsq_stock", leaf(stock, "dsq")), ("dsq_patched", leaf(pat, "dsq"))):
        Path(work, name + ".bin").write_bytes(data)
    shutil.copy(Path(__file__).with_name("lcd_fx3_qemu.c"), Path(work, "vdf.c"))
    subprocess.run(["arm-linux-gnueabi-gcc", "-static", "-mthumb", "-march=armv7-a", "-O2", "-Wall", "-Wextra", "-Werror", "vdf.c", "-o", "vdf"],
                   cwd=work, check=True)
    cs = cases()
    text = "".join("%s %d %d %d %d %d %d\n" % c[:7] for c in cs)
    out = subprocess.run(["qemu-arm", "-cpu", "cortex-a15", "./vdf"], cwd=work, input=text, text=True, stdout=subprocess.PIPE,
                         timeout=60, check=True).stdout.splitlines()
    assert len(out) == len(cs), (len(out), len(cs))
    rows = []
    for c, line in zip(cs, out):
        v = [int(x) for x in line.split()]
        rows.append({"fn": c[0], "patched": c[1], "panel": c[7], "aspect": c[5], "code": c[6], "fit": v[0], "rect": v[1:]})
    return rows


def compare(rows):
    emu = json.loads(EMU.read_text(encoding="utf8"))
    get = lambda fn, p, panel, asp, code: next(r["rect"] for r in rows if (r["fn"], r["patched"], r["panel"], r["aspect"], r["code"]) == (fn, p, panel, asp, code))
    n = 0
    for c in emu["cases"]:
        if c["what"].startswith("live view, de-squeeze off"):
            assert [get("ratio", 0, c["panel"], 2, 0), get("ratio", 1, c["panel"], 2, 0)] == [c["stock"], c["patched"]], c
            n += 1
        elif c["what"].startswith("de-squeeze code"):
            code = int(c["what"].split()[2])
            assert [get("dsq", 0, c["panel"], 2, code), get("dsq", 1, c["panel"], 2, code)] == [c["stock"], c["patched"]], c
            n += 1
    for r in rows:
        if r["fn"] == "ratio" and r["aspect"] != 2 or r["fn"] == "dsq" and r["code"] in (1, 2, 3) and r["aspect"] != 2:
            twin = get(r["fn"], 1 - r["patched"], r["panel"], r["aspect"], r["code"])
            assert twin == r["rect"], r
    assert all(r["fit"] == 3 for r in rows if r["aspect"] == 2)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", help="directory for the build (default: a new temporary directory)")
    ap.add_argument("--save", action="store_true")
    o = ap.parse_args()
    if o.work:
        Path(o.work).mkdir(parents=True, exist_ok=True)
        rows = run(o.work)
    else:
        with tempfile.TemporaryDirectory() as d:
            rows = run(d)
    n = compare(rows)
    qv = subprocess.check_output(["qemu-arm", "--version"], text=True).splitlines()[0]
    print(f"{len(rows)} qemu-arm cases; {n} Unicorn cases matched exactly; the shapes the design leaves alone are unchanged ({qv})")
    if o.save:
        (EMU.parent / "lcd32dsq_fx30_v1_qemu.json").write_text(json.dumps({"qemu": qv, "image_sha256": SHA, "leaves": {k: [hex(a), hex(b)] for k, (a, b) in LEAVES.items()},
                                                                          "matched_unicorn_cases": n, "rows": rows}, indent=1) + "\n", encoding="utf8")
        print("wrote", EMU.parent / "lcd32dsq_fx30_v1_qemu.json")
