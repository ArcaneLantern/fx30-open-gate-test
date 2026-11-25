"""The picture size the camera's MP4 writer puts in an open-gate file (libmpr.so 6.02): code sites, shared by build_ogfile.py and build_og57.py
(--meta) and checked by build/emu_mp4_meta.py. 2026-11-24, at the owner's request ("add the correct metadata tags inside the sony stream so we
dont have to remux with ffmpeg ... 5760x3840 and 3:2 instead of 3840x2160 16:9").

What an open-gate file says today, and what an ffmpeg remux changes (C0543 against C0543_fixed): the track header `tkhd` (display size),
the visual sample entry in `stsd` (hvc1 / avc1 width and height) and Sony's `PROF` uuid box (its video entry VPRF) all say 3840x2160; the
stream inside is 5760x3840 (or 3840x2560) with square pixels, so a file whose headers say the stream's size shows 3:2 with no aspect field.
Sony's XML in the file (NonRealTimeMeta: VideoLayout pixel / numOfVerticalLine / aspectRatio, VideoFrame videoCodec) is not changed here:
its size is the field the videoCodec name lookup (0x2504fc) is keyed on, and its aspect strings have no 3:2 (F201).

All three headers come from one place: the track config the writer set-up builds in 0x222b18 (called from 0x11f030 for a recording):
width at config +0x2a, height at +0x28, from immediates per format:
  0x222b90 / 0x222b94   `mov w6, #0x870` / `mov w7, #0xf00`   combs 0, 2 (and 9): XAVC S 4K, AVC
  0x222bdc / 0x222be0   `mov w6, #0x870` / `mov w7, #0xf00`   combs 5, 7: XAVC HS 4K, HEVC
Readers of that width and height (every halfword load of config +0x28/+0x2a in 0x220000-0x230000):
  0x226108  tkhd: width << 16, height << 16                                         any size
  0x2240cc  stsd entry: accepts widths 480, 640, 800, 1280, 1440, 1920, 3840, 4096, 7680, else returns 2 (track not built)
  0x225db8  PROF video entry: 0x2256fc profile id (by codec, width, chroma, frame rate, bit rate; else 3) and 0x225d30 pixel aspect (the
            same widths, else 3); on 3 the PROF entry is left out and 0x226108 does not finish the track (0x223cc0 skipped)
  0x222714  level label for PROF (by height, frame rate, bit rate): any other height gets a default; a label only
So 3840x2560 needs only the two heights; 5760x3840 also needs 5760 accepted by 0x2240cc and 0x225d30 (their 7680 compare -> 5760; 7680 is
no format of this camera) and 0x2256fc to take the UHD profile ids (its three width loads -> the constant 3840).
"""

MOVZ_W = lambda rd, imm: (0x52800000 | (imm << 5) | rd).to_bytes(4, "little")     # movz wRd, #imm (imm < 0x10000)

# (address, expected disassembly (mnemonic, operands), new instruction bytes for 2560 / 5760, why)
SIZE_SITES = {
    "avc_h": (0x222B90, ("mov", "w6, #0x870"), "MP4 track height, XAVC S 4K (AVC, combs 0, 2)"),
    "avc_w": (0x222B94, ("mov", "w7, #0xf00"), "MP4 track width, XAVC S 4K (AVC, combs 0, 2)"),
    "hevc_h": (0x222BDC, ("mov", "w6, #0x870"), "MP4 track height, XAVC HS 4K (HEVC, combs 5, 7)"),
    "hevc_w": (0x222BE0, ("mov", "w7, #0xf00"), "MP4 track width, XAVC HS 4K (HEVC, combs 5, 7)"),
}
WIDTH_SITES = [
    (0x224174, ("mov", "w1, #0x1e00"), "stsd entry set-up 0x2240cc: its 7680 compare -> 5760, so a 5760-wide entry is built (else it returns 2)"),
    (0x225D88, ("mov", "w0, #0x1e00"), "PROF pixel aspect 0x225d30: its 7680 compare -> 5760 (1:1), else it returns 3"),
]
PROFILE_SITES = [
    (0x225728, ("ldrh", "w3, [x1, #0x2a]"), "MOVW3", "PROF profile id 0x2256fc, AVC: width read -> the constant 3840 (the UHD ids)"),
    (0x225B64, ("ldrh", "w0, [x1, #0x2a]"), "MOVW0", "PROF profile id 0x2256fc, HEVC chroma code 2: width read -> the constant 3840"),
    (0x225BA8, ("ldrh", "w0, [x1, #0x2a]"), "MOVW0", "PROF profile id 0x2256fc, HEVC chroma code 1: width read -> the constant 3840"),
]


# FX3 7.02 (2026-11-25): the same writer, relinked (track config 0x21fec4, stsd entry 0x221464, PROF entry 0x223110, tkhd 0x223460, profile id
# 0x222a94, pixel aspect 0x223088, level label 0x21fad0: matched instruction by instruction against the A7 IV's, the track config 36 of 40 with
# its jump table rebuilt). Its two 4K heights; only 3840x2560 is a file of the FX3 kit.
# FX2 1.01 (2026-11-25, modding/FX2_PORT_ENCODER.md): the A7 IV's writer moved by -0x37b4 (track config 0x21f364, stsd entry 0x220918, PROF entry
# 0x222604, tkhd 0x222954, profile id 0x221f48, pixel aspect 0x22257c, level label 0x21ef60; matched instruction for instruction, the track
# config 155 of 160 with only its jump-table page offsets different). Its two 4K heights, at the A7 IV's places in the function.
OTHER_BUILDS = {"fx3_702": {"avc_h": (0x21FF3C, ("mov", "w6, #0x870"), "MP4 track height, XAVC S 4K (AVC)"),
                            "hevc_h": (0x220074, ("mov", "w6, #0x870"), "MP4 track height, XAVC HS 4K (HEVC)")},
                "fx2_101": {"avc_h": (0x21F3DC, ("mov", "w6, #0x870"), "MP4 track height, XAVC S 4K (AVC, combs 0, 2)"),
                            "hevc_h": (0x21F428, ("mov", "w6, #0x870"), "MP4 track height, XAVC HS 4K (HEVC, combs 5, 7)")},
                # FX30 6.01 (2026-11-26, modding/FX30_PORT_ENCODER.md): the FX3's writer 0x2c higher (track config 0x21fef0, stsd entry 0x221490,
                # PROF entry 0x22313c, tkhd 0x22348c, profile id 0x222ac0, pixel aspect 0x2230b4, level label 0x21fafc: each the FX3's whole body,
                # branch targets and page offsets aside).
                "fx30_601": {"avc_h": (0x21FF68, ("mov", "w6, #0x870"), "MP4 track height, XAVC S 4K (AVC)"),
                             "hevc_h": (0x2200A0, ("mov", "w6, #0x870"), "MP4 track height, XAVC HS 4K (HEVC)")}}


# A7C II 2.01 (2026-11-25): the A7 IV's writer moved as one block by -0x390c (track config 0x21f20c, stsd entry 0x2207c0, PROF entry 0x2224ac,
# tkhd 0x2227fc, profile id 0x221df0, pixel aspect 0x222424); every site found by 32 bytes of context, unique, same instruction. Both sizes
# (3840x2560 and 5760x3840), as on the A7 IV. Checked by build/emu_mp4_meta.py --build a7c2_201.
SHIFTED = {"a7c2_201": -0x390C}
# A1 II 4.00 (2026-11-26, modding/A1M2_PORT_ENCODER.md): the A7 IV's writer moved by +0x15c4 (track config 0x2240dc, stsd entry 0x225690, PROF entry
# 0x22737c); all seven size sites found by 68 bytes of context, unique, the same instruction. Checked by build/emu_mp4_meta.py --build a1m2_400.
SHIFTED["a1m2_400"] = 0x15C4


def sites(width, height, build="a7iv_602"):
    """[(address, new 4 bytes, expected (mnemonic, operands) of the stock instruction, note)] for a file of width x height."""
    if build in SHIFTED:
        return [(a + SHIFTED[build], new, want, why) for a, new, want, why in sites(width, height)]
    if build != "a7iv_602":
        assert (width, height) == (3840, 2560), "the open-gate file of the %s kit" % build
        s = OTHER_BUILDS[build]
        return sorted((s[k][0], MOVZ_W(6, height), s[k][1], s[k][2] + f": 2160 -> {height}") for k in ("avc_h", "hevc_h"))
    assert (width, height) in ((3840, 2560), (5760, 3840)), "the open-gate files of this project"
    out = [(SIZE_SITES[k][0], MOVZ_W(6, height), SIZE_SITES[k][1], SIZE_SITES[k][2] + f": 2160 -> {height}") for k in ("avc_h", "hevc_h")]
    if width != 3840:
        out += [(SIZE_SITES[k][0], MOVZ_W(7, width), SIZE_SITES[k][1], SIZE_SITES[k][2] + f": 3840 -> {width}") for k in ("avc_w", "hevc_w")]
        out += [(a, MOVZ_W(1 if "w1" in d[1] else 0, width), d, why) for a, d, why in WIDTH_SITES]
        out += [(a, MOVZ_W(3 if kind == "MOVW3" else 0, 3840), d, why) for a, d, kind, why in PROFILE_SITES]
    return sorted(out)


def guards(lm, site_list):
    """Guards for the code sites: the 8 bytes before and after each site that are not themselves a site (instructions as in the file)."""
    taken = {a for a, *_ in site_list}
    out = []
    for a, *_ in site_list:
        for g in (a - 8, a + 4):
            span = [x for x in range(g, g + 8, 4) if x not in taken]
            for x in span:
                if not any(o["file_off"] == hex(x) for o in out):
                    out.append({"file_off": hex(x), "bytes": lm[x:x + 4].hex()})
    return out


def check(lm, site_list):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    for a, new, want, _ in site_list:
        got = next(md.disasm(lm[a:a + 4], a))
        assert (got.mnemonic, got.op_str) == want, (hex(a), got.mnemonic, got.op_str, want)
        assert len(new) == 4 and next(md.disasm(new, a)).mnemonic == "mov"
