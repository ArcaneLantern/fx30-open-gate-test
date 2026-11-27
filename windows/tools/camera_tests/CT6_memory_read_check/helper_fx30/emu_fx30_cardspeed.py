"""Run the built FX30 6.01 card-speed libraries (build_fx30_cardspeed.sh: V18 check, V19 apply, V20 put back) in Unicorn against a model of
the camera's main process. Offline; no camera. (Session MR1, 2026-11-27; design cardspeed_off_fx30_v1, modding/CARD_SPEED_CHECK.md.)

  ..\\..\\..\\work\\venv\\Scripts\\python.exe -I -B emu_fx30_cardspeed.py

The model process is emu_fx30_flash.py's (helper/emu_built.py's Run with pread64 of /proc/self/mem): libmpr.so 6.01 at a load base, its
code segment and its data segment as the loader leaves them, with /proc/self/maps lines as the kernel gives them. A read outside the
model's memory answers EIO.
Cases: check on stock (READY), apply (DONE: exactly the two instructions change), apply again (NOTHING TO DO, no write), check when applied
(APPLIED), put back (DONE, every byte as stock, reverse order), put back on stock (NOTHING TO DO); refusals with nothing written: a byte of
the check changed (a threshold), the compare helper changed, the ELF header changed, a site holding a foreign instruction, the check in a
non-executable mapping, libmpr.so not mapped, no /proc/self/mem; a lost write (undo: back to stock); one site already applied (only the other
is written). Then END TO END: the libmpr.so code segment as V19 leaves it in the model is run through build/media_rate_check.py's emulation
of RateCheck::GetMediaTransferRateInh: check types 1..6 never inhibit, type 0 still refuses, and the stock bytes after V20 behave as stock.
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "helper"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "build"))
import emu_fx30_flash as F  # noqa: E402  (its process model: image, maps_text, Run, changed, poke)
import media_rate_check as M  # noqa: E402

LIBMPR = ROOT / "work/extracted/fx30_601/0700_part_image/dev/nflasha15/lib/libmpr.so"
DESIGN = json.loads((ROOT / "modding/designs/cardspeed_off_fx30_v1.json").read_text(encoding="utf8"))
BASE = 0x7F90000000
RESULT = F.RESULT


def model():
    mem, rows = F.image(LIBMPR, BASE)
    return mem, rows


def sites():
    return {BASE + int(s["va"], 16): (bytes.fromhex(s["stock"]), bytes.fromhex(s["new"])) for s in DESIGN["sites"]}


def run(level, mem, rows, drop=(), pwrite_lost=()):
    files = {"/proc/self/maps": F.maps_text(rows), "/proc/self/mem": b""}
    for k in drop:
        files.pop(k, None)
    lib = (HERE / ("libJit_fx30_V%d.so" % level)).read_bytes()
    r = F.Run(lib, level, files, {"/tmp_wbshd"}, own=mem)
    r.preads = []
    r.pwrite_lost = set(pwrite_lost)
    r.go()
    after = {a: bytes(r.uc.mem_read(a, len(b))) for a, b in mem.items()}
    return r, r.writes.get(RESULT, b"").decode("utf8", "replace"), after


def semantic(after):
    """Run the check as the model's memory holds it (code segment at BASE) through media_rate_check's emulation."""
    lib = M.Lib(LIBMPR)
    seg0 = after[BASE]
    patches = []
    for k in range(0, len(seg0), 4):
        if seg0[k:k + 4] != lib.data[k:k + 4]:
            patches.append((k, seg0[k:k + 4]))
    fa = lib.syms[[n for n in lib.syms if n.startswith(M.SYM_PREFIX) and "GetMediaTransferRateInh" in n][0]][0]
    offsets, _ = M.learn_offsets(lib, fa)
    return patches, M.summarise_types(M.measure(lib, fa, offsets, patches))


def main():
    mem0, rows = model()
    S = sites()
    target = dict(mem0)
    for a, (_, new) in S.items():
        target = F.poke(target, a, new)
    results, fails = [], 0

    def ok(cond, what, text=""):
        nonlocal fails
        results.append({"case": what, "pass": bool(cond)})
        print(("PASS " if cond else "FAIL ") + what)
        if not cond:
            fails += 1
            print("   " + "\n   ".join(text.splitlines()[-12:]))

    r, t, m = run(18, mem0, rows)
    ok(not r.bad and "verdict: READY" in t and t.startswith("readcheck 1 level 18") and "== done" in t and not F.changed(mem0, m), "V18 on stock: READY, nothing written", t)
    r, t, m = run(19, mem0, rows)
    ch = F.changed(mem0, m)
    ok(not r.bad and "DONE: every site holds the target bytes (apply)" in t and m == target and set(ch) == set(S) and len(r.pwrites) == len(S),
       "V19 on stock: DONE, exactly the %d instructions written, nothing else" % len(S), t)
    ok([w[0] for w in r.pwrites] == sorted(S), "V19 order: the sites in address order")
    applied_mem = m
    r, t, m = run(19, target, rows)
    ok(not r.bad and "NOTHING TO DO" in t and m == target and not r.pwrites, "V19 when applied: NOTHING TO DO, no write", t)
    r, t, m = run(18, target, rows)
    ok(not r.bad and "verdict: APPLIED" in t and m == target, "V18 when applied: APPLIED", t)
    r, t, m = run(20, target, rows)
    ok(not r.bad and "DONE: every site holds the target bytes (put back)" in t and m == mem0 and len(r.pwrites) == len(S), "V20 when applied: DONE, every byte as stock", t)
    ok([w[0] for w in r.pwrites] == sorted(S, reverse=True), "V20 order: the reverse of V19")
    putback_mem = m
    r, t, m = run(20, mem0, rows)
    ok(not r.bad and "NOTHING TO DO" in t and m == mem0 and not r.pwrites, "V20 on stock: NOTHING TO DO", t)

    def refused(mem, what, rws=rows, **kw):
        r, t, m = run(19, mem, rws, **kw)
        ok(not r.bad and "nothing is written" in t and "DONE" not in t and not r.pwrites and m == mem, "V19 refuses (%s): nothing is written" % what, t)
        r, t, m = run(18, mem, rws, **kw)
        ok(not r.bad and "verdict: NOT READY" in t and m == mem, "V18 says NOT READY (%s)" % what, t)

    assert mem0[BASE][0x103E7C:0x103E80] == bytes.fromhex("004b8052")               # mov w0, #0x258 (600: the V90 threshold)
    refused(F.poke(mem0, BASE + 0x103E7C, bytes.fromhex("00328052")), "the V90 threshold changed (mov w0, #600 -> #400)")
    refused(F.poke(mem0, BASE + 0x103C68, bytes(4)), "the compare helper changed")
    refused(F.poke(mem0, BASE + 0x10, b"\x09"), "the ELF header changed")
    first = min(S)
    refused(F.poke(mem0, first, bytes.fromhex("1f2003d6")), "a site holding a foreign instruction")
    noexec = [(lo, hi, "r--p" if p == "r-xp" else p, off, n) for lo, hi, p, off, n in rows]
    refused(mem0, "the check in a non-executable mapping", rws=noexec)
    no_mpr = [row for row in rows if "libmpr" not in row[4]]
    r, t, m = run(19, mem0, no_mpr)
    ok(not r.bad and "libmpr.so is not mapped" in t and not r.pwrites and m == mem0, "V19 with libmpr.so not in /proc/self/maps: nothing is written", t)
    r, t, m = run(19, mem0, rows, drop=("/proc/self/mem",))
    ok(not r.bad and "/proc/self/mem open failed" in t and not r.pwrites and m == mem0, "V19 without /proc/self/mem: nothing is written", t)
    r, t, m = run(19, mem0, rows, pwrite_lost=[max(S)])
    ok(not r.bad and "NOT DONE: a step failed; every site this run touched was put back" in t and m == mem0, "V19 with a lost write: NOT DONE, everything put back", t)
    half = F.poke(mem0, first, S[first][1])
    r, t, m = run(19, half, rows)
    ok(not r.bad and "DONE" in t and m == target and len(r.pwrites) == 1 and r.pwrites[0][0] == max(S), "V19 with one site applied: only the other is written", t)
    r, t, m = run(18, half, rows)
    ok(not r.bad and "verdict: NOT READY" in t, "V18 with one site applied: NOT READY (mixed)", t)

    # end to end: the instructions V19 leaves in the model, run as code
    patches, after = semantic(applied_mem)
    ok(sorted(a for a, _ in patches) == sorted(int(s["va"], 16) for s in DESIGN["sites"]) and all(b == M.NOP for _, b in patches),
       "after V19 the code segment differs from the file in exactly the two sites, each a NOP")
    ok(all(after[t]["fs4"] == "passes at any rate" and after[t]["fs3"] == "passes at any rate" for t in range(1, 7)),
       "after V19 check types 1..6 (Class 10 .. VPG400) pass for any card rate and filesystem", json.dumps(after))
    ok(after[0]["fs4"].startswith("fails at any rate: 0x400") and after[7]["fs4"].startswith("fails at any rate: 0x400"),
       "after V19 a setting missing from the tables (type 0) is still refused (0x400)", json.dumps(after))
    patches2, stock_after = semantic(putback_mem)
    ok(not patches2 and stock_after[4]["fs4"] == "passes from 601 Mbps, else 0x4000" and stock_after[4]["fs3"].startswith("fails at any rate"),
       "after V20 the check is stock again (V90: from 601 Mbps on exFAT)", json.dumps(stock_after))
    out = {"about": "helper_fx30/emu_fx30_cardspeed.py: the built V18/V19/V20 libraries in Unicorn against a model of the camera's main process, "
                    "then the patched check run as code",
           "libraries": {n: hashlib.sha256((HERE / ("libJit_fx30_%s.so" % n)).read_bytes()).hexdigest() for n in ("V18", "V19", "V20")},
           "check_types_after_v19": after, "cases": results, "failed": fails}
    (ROOT / "evidence/media_rate/emu_fx30_cardspeed.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("%d cases, %d failed" % (len(results), fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
