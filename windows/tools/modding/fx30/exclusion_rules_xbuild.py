"""Decode the exclusion-manager rule tables (Sony "HAITA") in appFw.so of ANY indexed build, finding the tables by
themselves (session HS1, hot shoe and flash study).

The layout is the one documented in build/decode_exclusion_rules.py (finding F502, A7 IV 6.02 addresses hard-coded
there; that script is left untouched):
  names       pointer array, one entry per id: PRM_... parameters, then FUNC_... ids (newer builds), then VAL_... values
  ranges      12 bytes per parameter: first value id, last value id, a byte (1 = matched by function)
  by source   16 bytes per parameter: {pointer to an array of rule pointers, count}
  rule        +0 pointer to one entry per source value -> {pointer to actions, count} or 0; +8 target; +0xc source
  action      12 bytes {kind, flag, -, -, a, b}: kind 0/6/7 inhibit value a; 1 force target to b; 2/9 map a -> b
A source above the last PRM id (a FUNC_ id, or above 0xd0c on the A7 IV) has one action list whatever its value.

How the tables are found (no addresses are hard-coded):
  names       the pointer array that holds the pointer to "PRM_FEATURE_MANAGER_camera_parameters" and runs longest
  ranges      the 4-byte-aligned position where parameter 0 starts at the first VAL_ id and the ranges ascend
  by source   the 8-byte-aligned position where the entries for still shutter type and flash mode both point to rules
              whose +0xc field is that parameter
Virtual addresses are converted to file offsets with the ELF program headers.

  python -I -B build/exclusion_rules_xbuild.py <build> [--selftest]
      writes evidence/hotshoe/exclusion_<build>.json: table addresses, totals, every rule and action whose source or
      target is a flash, shoe, shutter-type, silent, drive or feature-manager-flash parameter, with rule and action
      addresses. --selftest (a7iv_602 only) checks F502's totals (23,171 rules, 525,325 actions) and exits.
  python -I -B build/exclusion_rules_xbuild.py <build> --target NAME[,NAME...]   print every action on those parameters
  python -I -B build/exclusion_rules_xbuild.py <build> --source NAME[,NAME...]   print every action they cause
Names are exact parameter names (PRM_...). Read-only on firmware; writes only the evidence JSON.
"""
import collections
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import locate_file  # noqa: E402

FLASH_KW = ("flash", "strobe", "shoe", "wireless", "red_eye")            # a parameter about the flash or the shoe
SHUT_KW = ("shutter_type", "silent", "mecha", "curtai", "re_throwing", "anti_distortion", "hybrid", "elec_strobe")
KEYWORDS = FLASH_KW + SHUT_KW
KIND = {0: "inhibit", 6: "inhibit", 7: "inhibit", 1: "force", 2: "map", 9: "map", 3: "k3", 4: "k4", 5: "k5", 8: "k8"}


class Elf:
    def __init__(self, data):
        self.d = data
        assert data[:4] == b"\x7fELF" and data[4] == 2, "64-bit ELF expected"
        phoff, = struct.unpack_from("<Q", data, 0x20)
        phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
        self.loads = []
        for i in range(phnum):
            p_type, _flags, off, vaddr, _pa, filesz, _memsz, _al = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
            if p_type == 1:
                self.loads.append((vaddr, vaddr + filesz, off))
        self.rw_start = self.loads[1][0] if len(self.loads) > 1 else 0
        self.ro_end = self.loads[0][1]

    def off(self, va):
        for lo, hi, off in self.loads:
            if lo <= va < hi:
                return off + va - lo
        return -1

    def va_of(self, off):
        for lo, hi, o in self.loads:
            if o <= off < o + hi - lo:
                return lo + off - o
        return -1

    def u64(self, va):
        o = self.off(va)
        return struct.unpack_from("<Q", self.d, o)[0] if o >= 0 and o + 8 <= len(self.d) else 0

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.d, o)[0] if o >= 0 and o + 4 <= len(self.d) else 0

    def i32(self, va):
        o = self.off(va)
        return struct.unpack_from("<i", self.d, o)[0] if o >= 0 and o + 4 <= len(self.d) else -99

    def cstr(self, va, limit=2000):                         # some rule names exceed 300 characters
        o = self.off(va)
        if o < 0:
            return ""
        e = self.d.find(b"\0", o, o + limit)
        return self.d[o:e].decode("ascii", "replace") if e > 0 else ""


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def decode(build):
    path = locate_file.locate(build, "appFw.so")
    e = Elf(path.read_bytes())
    d = e.d
    in_ro = lambda p: 0x1000 < p < e.ro_end
    # 1. names
    so = d.find(b"\0PRM_FEATURE_MANAGER_camera_parameters\0") + 1
    assert so > 0, "name string not found"
    target = struct.pack("<Q", e.va_of(so))
    best = None
    for m in re.finditer(re.escape(target), d):
        va = e.va_of(m.start())
        if m.start() % 8 or not (e.loads[1][0] <= va < e.loads[1][1]):    # the array is in the data segment (skip RELA addends)
            continue
        s = va
        while in_ro(e.u64(s - 8)) and e.cstr(e.u64(s - 8)).startswith("PRM_"):
            s -= 8
        n, v = 0, s
        while in_ro(e.u64(v)) and IDENT.fullmatch(e.cstr(e.u64(v)) or "-"):
            v += 8
            n += 1
        if best is None or n > best[1]:
            best = (s, n)
    names_va, count = best
    name = {i: e.cstr(e.u64(names_va + 8 * i)) for i in range(count)}
    first_func = next((i for i in range(count) if name[i].startswith("FUNC_")), None)
    first_val = next(i for i in range(count) if name[i].startswith("VAL_"))
    last_prm = (first_func if first_func is not None else first_val) - 1
    n_par = first_val
    ids = {v: k for k, v in name.items() if v.startswith(("PRM_", "FUNC_"))}
    # 2. ranges
    ranges_off, best_score = None, -1
    for m in re.finditer(re.escape(struct.pack("<i", first_val)), d):
        o = m.start()
        if o % 4 or o + 12 * n_par > len(d):
            continue
        a, b = struct.unpack_from("<ii", d, o)
        a2, = struct.unpack_from("<i", d, o + 12)
        if not (b >= a and a2 == b + 1):
            continue
        score, prev = 0, -1
        for p in range(min(n_par, 600)):
            x, y, z = struct.unpack_from("<iiI", d, o + 12 * p)
            if z < 2 and (x == -1 or (x > prev and y >= x)):
                score += 1
                prev = max(prev, y)
            else:
                break
        if score > best_score:
            best_score, ranges_off = score, o
    ranges_va = e.va_of(ranges_off)
    rng = [struct.unpack_from("<iiB", d, ranges_off + 12 * p) for p in range(n_par)]
    # 3. rules by source
    p1, p2 = ids["PRM_setting_still_shutter_type"], ids["PRM_setting_flash_mode"]
    rw_lo, rw_hi = e.loads[1][0], e.loads[1][1]

    def entry_ok(x, p):
        arr, c = e.u64(x + 16 * p), e.i32(x + 16 * p + 8)
        if not (rw_lo <= arr < rw_hi) or not (0 < c < 3000):
            return False
        r = e.u64(arr)
        return rw_lo <= r < rw_hi and e.i32(r + 0xC) == p
    by_source = None
    for x in range(rw_lo - rw_lo % 8, rw_hi, 8):
        if entry_ok(x, p1) and entry_ok(x, p2):
            by_source = x
            break
    assert by_source, "rules-by-source table not found"
    actions, rules = [], []
    for src in range(n_par):
        arr, cnt = e.u64(by_source + 16 * src), e.u32(by_source + 16 * src + 8)
        if not arr:
            continue
        first, last, _ = rng[src]
        for k in range(cnt):
            rule = e.u64(arr + 8 * k)
            tab, tgt, source = e.u64(rule), e.i32(rule + 8), e.i32(rule + 0xC)
            assert source == src, (hex(rule), src, source)
            rules.append((rule, src, tgt))
            values = [(-1, 0)] if src > last_prm or first < 0 else [(first + vi, vi) for vi in range(last - first + 1)]
            for sv, vi in values:
                info = e.u64(tab + 8 * vi)
                if not info:
                    continue
                ap, an = e.u64(info), e.u32(info + 8)
                for j in range(an):
                    o = e.off(ap + 12 * j)
                    kind, flag = d[o], d[o + 1]
                    a, b = struct.unpack_from("<ii", d, o + 4)
                    actions.append({"rule": rule, "src": src, "sv": sv, "tgt": tgt, "kind": kind, "flag": flag, "a": a, "b": b,
                                    "at": ap + 12 * j})
    return {"build": build, "path": str(path), "e": e, "name": name, "ids": ids, "rng": rng, "n_par": n_par,
            "last_prm": last_prm, "first_func": first_func, "first_val": first_val, "names_va": names_va,
            "ranges_va": ranges_va, "by_source": by_source, "rules": rules, "actions": actions}


def short(t, v):
    return "any value" if v == -1 else t["name"].get(v, hex(v)).replace("VAL_", "").replace("PRM_", "")


def values_of(t, p):
    a, b, _ = t["rng"][p]
    if a < 0 or b - a > 60:
        return None
    return [short(t, v).replace(short(t, p) + "_", "") for v in range(a, b + 1)]


def describe(t, act):
    s, tg = short(t, act["src"]), short(t, act["tgt"])
    kind = act["kind"]
    if kind == 1:
        val = short(t, act["b"]).replace(tg + "_", "")
    elif kind in (2, 9):
        val = f"{short(t, act['a']).replace(tg + '_', '')} -> {short(t, act['b']).replace(tg + '_', '')}"
    else:
        val = short(t, act["a"]).replace(tg + "_", "")
    return {"rule": hex(act["rule"]), "action_at": hex(act["at"]), "action_file_offset": hex(t["e"].off(act["at"])),
            "source": s, "source_value": short(t, act["sv"]).replace(s + "_", ""), "target": tg, "effect": KIND.get(kind, kind),
            "kind": kind, "flag": act["flag"], "value": val}


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    build = args[0]
    t = decode(build)
    n_rules, n_act = len(t["rules"]), len(t["actions"])
    head = (f"{build}: names {t['names_va']:#x} ({len(t['name'])} ids, last PRM {t['last_prm']:#x}, first FUNC "
            f"{t['first_func'] if t['first_func'] is None else hex(t['first_func'])}, first VAL {t['first_val']:#x}), "
            f"ranges {t['ranges_va']:#x}, by source {t['by_source']:#x}: {n_rules} rules, {n_act} actions")
    print(head)
    if "--selftest" in args:
        assert build == "a7iv_602", "the self-test uses F502's A7 IV totals"
        assert (n_rules, n_act) == (23171, 525325), (n_rules, n_act)
        print("selftest OK: F502 totals reproduced")
        return
    if "--target" in args or "--source" in args:
        col = "tgt" if "--target" in args else "src"
        want = args[args.index("--target" if col == "tgt" else "--source") + 1].split(",")
        pick = {t["ids"][w] for w in want if w in t["ids"]}
        for p in sorted(pick):
            print("parameter", hex(p), t["name"][p], values_of(t, p))
        grouped = collections.defaultdict(list)
        for act in t["actions"]:
            if act[col] in pick:
                r = describe(t, act)
                grouped[(r["target"], r["effect"], r["value"])].append(f"{r['source']} = {r['source_value']}  (rule {r['rule']}, action {r['action_at']})")
        for (tg, eff, val), conds in sorted(grouped.items()):
            print(f"\n{tg}: {eff} {val}   ({len(conds)})")
            for c in conds[:60]:
                print("    while", c)
        return
    has = lambda p, kws: any(k.lower() in t["name"].get(p, "").lower() for k in kws)
    fl = {p for p in range(t["n_par"]) if has(p, FLASH_KW)}
    sh = {p for p in range(t["n_par"]) if has(p, SHUT_KW)}
    rel = fl | sh
    params = [{"id": hex(p), "name": t["name"][p], "values": values_of(t, p), "matched_by_function": bool(t["rng"][p][2])}
              for p in sorted(rel)]
    # kept: every action ON a flash/shoe parameter, and every action of a flash/shoe parameter ON a shutter parameter;
    # the bookkeeping kinds 4/5 are left out
    rows = [describe(t, a) for a in t["actions"] if a["kind"] not in (4, 5) and
            (a["tgt"] in fl or (a["src"] in fl and a["tgt"] in sh))]
    kinds = collections.Counter(a["kind"] for a in t["actions"])
    out = {"about": "Exclusion-manager (HAITA) rules in appFw.so whose source or target is a flash, shoe, shutter-type, silent, "
                    "drive, interval or feature-manager parameter. Generated by build/exclusion_rules_xbuild.py (session HS1); "
                    "addresses are virtual addresses in appFw.so, action_file_offset is the offset in the file. Rows: every "
                    "action whose target is a flash/strobe/shoe/wireless/red-eye parameter, plus actions of those "
                    "parameters on shutter-type parameters; bookkeeping kinds 4 and 5 are left out.",
           "build": build, "file": t["path"].split("extracted")[-1], "names_table": hex(t["names_va"]), "ids": len(t["name"]),
           "last_prm": hex(t["last_prm"]), "first_func": None if t["first_func"] is None else hex(t["first_func"]),
           "first_val": hex(t["first_val"]), "ranges_table": hex(t["ranges_va"]), "rules_by_source": hex(t["by_source"]),
           "rules": n_rules, "actions": n_act, "actions_by_kind": dict(sorted(kinds.items())),
           "feature_manager_parameters": [t["name"][p] for p in range(t["n_par"]) if "FEATURE_MANAGER" in t["name"][p]],
           "parameters": params, "rows": rows}
    dst = ROOT / "evidence" / "hotshoe" / f"exclusion_{build}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"{len(params)} parameters, {len(rows)} actions written to {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
