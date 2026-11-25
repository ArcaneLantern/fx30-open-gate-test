"""FX30 (ILME-FX30) firmware 6.01: apply, or put back, the open-gate state in the camera's MEMORY.

  python fx30_apply.py apply    [--no-screen] [--no-meta] [--dry-run]
  python fx30_apply.py putback  [--no-screen] [--dry-run]
  python fx30_apply.py screen | screen-putback  [--dry-run]
  python fx30_apply.py playback | playback-putback  [--dry-run]      (optional, NOT RUN ON ANY CAMERA: in-camera playback)
  (apply and screen take --no-movie-session to leave out the closing read-only session)

The FX30 port (2026-11-26) of the open-gate state that works on the A7 IV, A7S III and FX3: a true 3840x2560 file of the 3:2 area of
the sensor, shown at 3:2 on the rear screen. NOTHING OF THIS KIT HAS RUN ON AN FX30. How it is built (modding/FX30_PORT.md):
  - The FX30 reads its 4K (6K-oversampled) picture from a 5952x3348 window of the sensor. The sensor's settings for that window are the
    same as for every other 6K window; only the window's position and height come from tables. L5 makes the window 5952x3968 (3:2) from
    row 96, centred where the 16:9 one is, in the five drive modes that share the 4K picture records (0x820, 0x880, 0x890, 0x8c0, 0x8d0),
    keeps the 4K mode's own line timing, and squeezes it into the stock 4336x2438 first-stage picture (the A7 IV's ogsq_v3 method).
  - L16 makes the 4K output 3840x2560; L19 sets up the encoder and the MP4 headers for it (the FX3 kit's encoder step, moved);
  - S16 shows the 3:2 picture on the rear screen and sets the camera's own De-Squeeze Display ratios for it (the FX3 kit's screen step).
  - No raw-write-buffer step: the FX30's stock buffer already holds the taller first stage.

  apply    four steps, each its own USB session: L5 sensor side (ogsq_fx30_v1), L16 output size (outsz2560_fx30_v1), L19 encoder side
           (ogfile2560_hs_s_fx30_v2), S16 rear screen at 3:2 with the focus frames and De-Squeeze Display set for the 3:2 picture
           (lcd32dsq_fx30_v1). --no-screen leaves out S16; --no-meta uses N19 (the MP4 headers keep 3840x2160). A step that finds
           its bytes already applied says NOTHING TO DO and counts as passed.
  putback  the reverse: S17, L20, L17, L6 (--no-screen leaves out S17). A cold boot (battery out for 10 seconds) also undoes everything.
  screen / screen-putback   only the screen step (S16) or its put back (S17).
  playback / playback-putback   only the playback step (P29) or its put back (P30), NOT RUN ON ANY CAMERA. Like the FX3, the FX30 opens
           every playback decoder at 4096x2160, so a 3840x2560 clip is expected not to play ("Unable to display"). P29 makes it open the A7 IV's
           7690x4320 channel with its memory (avdec8k_fx30_v1). It changes four instructions of av-cam.bin (kernel code) and one table word;
           the library refuses unless the processors' caches can be made to fetch the new instructions. Independent of the open-gate steps.

The closing session (apply and screen): the script asks for Movie and an unplug and replug and runs the read-only dump itself, which reads
what the five stored records program (the window), the panel type, and the screen state. Nothing is written in that session.

Rules it keeps:
- It starts only if the newest saved read-only check of this kit says VERDICT READY.
- It stops at the first step that does not end in DONE or NOTHING TO DO, and says what state that leaves.
- Each step is one pinned library; the runner (fx30_run.py) refuses any other bytes.
Nothing is written to a firmware file or to the camera's settings. What is written lives in the running camera's memory. A cold
boot (battery out for 10 seconds) removes it. On the A7S III the power switch removed it as well, so keep the FX30 switched on from
the first step to the last.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE))
import ct1_common as c  # noqa: E402
import fx30_run  # noqa: E402

FIRMWARE = fx30_run.FIRMWARE
STEPS = {"apply": ("L5", "L16", "L19"), "putback": ("L20", "L17", "L6"), "screen": ("S16",), "screen-putback": ("S17",),
         "playback": ("P29",), "playback-putback": ("P30",)}
RUNNER = HERE / "fx30_run.py"
LISTER = HERE.parent / "CT1_usb_first_contact" / "ct1_stage2_service.py"
STILL = "a still-image mode (press MODE, choose Program Auto, Aperture Priority, Shutter Priority or Manual Exposure with the control wheel, press its centre)"
MOVIE = "Movie (press MODE, choose Movie with the control wheel, press its centre; File Format XAVC HS 4K or XAVC S 4K, 24p (25p under PAL))"


def say(text=""):
    print(text, flush=True)


def sessions():
    """Saved sessions of this kit, newest first: (folder, manifest)."""
    root = c.PRIVATE_ROOT
    out = []
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
            try:
                out.append((folder, json.loads((folder / "manifest.json").read_text(encoding="utf8"))))
            except (OSError, ValueError):
                continue
    return out


def last_check():
    """The newest saved read-only check of this kit that fetched a result: (folder name, ready?) or None. A check that stopped before the
    camera answered says nothing and is skipped. A check made with another kit does not count: its header is not this helper's."""
    for folder, man in sessions():
        res = man.get("results", {})
        f = (res.get("ct6", {}).get("result") or {}).get("s3")
        if res.get("which") in ("check", "dump") and f:       # a dump makes every check the check makes, and gives the same verdict
            current = "fx30read_v1 " in f.get("header", "") and "ILME-FX30 6.01" in f.get("header", "")
            return folder.name, current and bool(f.get("ready")) and not f.get("identity_differs")
    return None


def last_result_sha():
    """The SHA-256 of the result the newest session fetched: the runner deletes a result left on the RAM disk only if it has this hash."""
    for _, man in sessions():
        try:
            return man["results"]["ct6"]["result"]["sha256"]
        except (KeyError, TypeError):
            continue
    return None


def usb_state():
    r = subprocess.run([sys.executable, "-I", "-B", str(LISTER), "--list"], capture_output=True, text=True, encoding="utf8", errors="replace", cwd=str(LISTER.parent))
    import re
    m = re.search(r"libusb sees: (\d+) Sony mass-storage device\(s\).*?, (\d+) Sony service device\(s\)", r.stdout)
    if not m:
        return "other"
    return "drive" if int(m.group(1)) == 1 and int(m.group(2)) == 0 else "service" if int(m.group(2)) else "other"


def wait_for_drive(first, timeout=600):
    asked, end = False, time.time() + timeout
    while usb_state() != "drive":
        if not asked:
            say()
            if first:
                say("The camera is not showing as a USB drive. Turn it on, in %s, connect USB (USB Connection Mode: Mass Storage)." % STILL)
            else:
                say(">>> Unplug the USB cable from the camera and plug it in again.")
                say(">>> Do NOT power the camera off or pull the battery: that would leave the steps half done.")
            say("Waiting for the camera (Ctrl+C to stop) ...")
            asked = True
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def wait_for_replug(timeout=900):
    """Wait until the camera has been unplugged and shows up as a USB drive again. False on timeout."""
    end = time.time() + timeout
    while usb_state() != "other":                    # still plugged in, as a drive or in service mode
        if time.time() > end:
            return False
        time.sleep(1)
    while usb_state() != "drive":
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def movie_session():
    """The closing read-only session, taken in movie mode."""
    say()
    say("=" * 78)
    say("One more session, and it only READS: it records what the camera holds after the apply, for the report.")
    say(">>> 1. Unplug the USB cable.")
    say(">>> 2. Set %s." % MOVIE)
    say("       Look at the rear screen for five seconds and remember it: the whole 3:2 picture, or anything odd (lines, colours, black parts)?")
    say(">>> 3. Plug the USB cable in again, still in Movie.")
    say(">>> Do NOT switch the camera off: on the A7S III the power switch removed the patch.")
    say("Waiting for the unplug and the replug (Ctrl+C to stop; the patch stays applied either way) ...")
    if not wait_for_replug():
        say("The camera did not come back as a USB drive. The steps are applied all the same.")
        return
    cmd = [sys.executable, "-I", "-B", str(RUNNER), "dump", "--go", "--firmware-shown", FIRMWARE]
    clear = last_result_sha()
    if clear:
        cmd += ["--clear-result", clear]
    rc = subprocess.run(cmd).returncode
    which, f = step_outcome()
    say()
    if rc or which != "dump" or not f:
        say("The read-only session did not finish. The steps are applied all the same.")
        return
    decoded = f.get("decoded") or {}
    wins = decoded.get("design_mode_windows") or {}
    w = wins.get("0x8c0")
    if w:
        say("The 4K 24p mode's stored record programs a %d-row window from sensor row %d (%s; stock 3348 rows from row 406)." % (w["window"][0], w["window"][1], w["state"]))
    panel = (decoded.get("display") or {}).get("panel_types")
    if panel:
        say("The rear panel reports type %d (%s). Please send this folder: it settles the FX30's panel shape." % (panel["rear_0x16295d4"], panel["rear_aspect"]))
    say(">>> Unplug USB now.")


def step_outcome():
    for _, man in sessions():
        f = man.get("results", {}).get("ct6", {}).get("result", {}).get("s3")
        return (man.get("results", {}).get("which"), f) if f else (None, None)
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=sorted(STEPS))
    ap.add_argument("--dry-run", action="store_true", help="show the steps and what each would send; nothing is sent")
    ap.add_argument("--no-screen", action="store_true", help="with apply or putback: without the screen step (S16 / S17)")
    ap.add_argument("--no-movie-session", action="store_true", help="with apply or screen: leave out the closing read-only session in movie mode")
    ap.add_argument("--no-meta", action="store_true", help="with apply: the encoder step without the MP4 header heights (N19); the headers keep saying 3840x2160")
    a = ap.parse_args()
    steps = STEPS[a.what]
    if a.no_screen and a.what not in ("apply", "putback"):
        raise SystemExit("--no-screen goes with apply or putback. Nothing was sent.")
    if a.no_meta and a.what != "apply":
        raise SystemExit("--no-meta goes with apply (the put back L20 puts back either encoder step). Nothing was sent.")
    if a.no_meta:
        steps = tuple("N19" if k == "L19" else k for k in steps)
    with_screen = not a.no_screen
    if a.what in ("apply", "putback") and with_screen:
        steps = steps + STEPS["screen"] if a.what == "apply" else STEPS["screen-putback"] + steps
    applying = a.what in ("apply", "screen", "playback")
    closing = a.what in ("apply", "screen")           # the closing read-only session in Movie: only after the open-gate or screen steps
    for k in steps:                                  # every library must be the pinned one before anything starts
        name, sha, _ = fx30_run.WRITE_STEPS[k]
        p = fx30_run.S3 / name
        if not p.is_file() or c.sha256(p.read_bytes()) != sha:
            raise SystemExit("%s is missing or is not the pinned build. Nothing was sent." % name)
    say("FX30 6.01, %s: %d steps" % (a.what, len(steps)))
    for n, k in enumerate(steps, 1):
        say("  %d. %s  %s  (library %s...)" % (n, k, fx30_run.WRITE_STEPS[k][2], fx30_run.WRITE_STEPS[k][1][:16]))
    if closing and not a.no_movie_session:
        say("  then one read-only session (dump) in Movie: it records the state for the report. Nothing is written in it.")
    if a.dry_run:
        for k in steps:
            say()
            say("--- %s, what the session would send:" % k)
            r = subprocess.run([sys.executable, "-I", "-B", str(RUNNER), k, "--dry-run"], capture_output=True, text=True, encoding="utf8", errors="replace")
            say(r.stdout.rstrip() or r.stderr.rstrip())
        say()
        say("Dry run only: nothing was sent to any device.")
        return
    chk = last_check()
    if applying and (chk is None or not chk[1]):
        raise SystemExit("The newest saved read-only check of this kit %s. Run check_readonly first and get VERDICT READY. Nothing was sent."
                         % ("does not exist" if chk is None else "(%s) does not say READY" % chk[0]))
    say()
    say("This WRITES into the running camera's memory (not its firmware, not its settings).")
    if a.what in ("playback", "playback-putback"):
        say("The playback step is NEW and has NOT RUN ON ANY CAMERA. It changes four instructions of av-cam.bin (the kernel's AV code) and one")
        say("  word of its decode table. Its library checks the whole code page against the firmware file, reads the processors' cache type,")
        say("  and refuses unless it can make every processor fetch the new instructions; it then writes the instructions first and the")
        say("  table word last (put back: the table word first). If anything is not as expected it writes nothing.")
    elif applying:
        say("NOTHING OF THIS KIT HAS RUN ON AN FX30 YET. The same method works on the A7 IV, A7S III and FX3; on the FX30 every step was")
        say("  checked against the FX30's own firmware code in emulation only. Possible outcomes are listed in README.md.")
    else:
        say("It has to follow an apply of this kit.")
    say("A cold boot (battery out for 10 seconds) returns the camera to stock. On the A7S III the power switch did too:")
    say("so KEEP THE CAMERA SWITCHED ON from now until the script says it is finished.")
    if a.what in ("playback", "playback-putback"):
        say("Before you go on: a charged battery, %s, and the camera NOT in playback (no clip open)." % STILL)
    elif a.what == "apply":
        say("Before you go on: %s, a charged battery," % STILL)
        say("and a camera that was cold booted and has not been in Movie or S&Q since. (If it starts in Movie: choose a still mode,")
        say("pull the battery for 10 seconds, put it back and switch on: it starts in the still mode.)")
        say("(If the open-gate state is already applied in this power-on, its steps will say NOTHING TO DO: that is fine.)")
    else:
        say("Before you go on: a charged battery, and %s." % STILL)
    if input("Firmware version in the camera's menu: ").strip() != FIRMWARE:
        raise SystemExit("Not %s. Nothing was sent." % FIRMWARE)
    if input("Type YES to write to the camera's memory: ").strip() != "YES":
        raise SystemExit("Not confirmed. Nothing was sent.")
    for n, k in enumerate(steps, 1):
        if not wait_for_drive(n == 1):
            raise SystemExit("The camera did not show up as a USB drive. Stopped before step %d (%s)." % (n, k))
        say()
        say("=" * 78)
        say("Step %d of %d: %s, %s" % (n, len(steps), k, fx30_run.WRITE_STEPS[k][2]))
        cmd = [sys.executable, "-I", "-B", str(RUNNER), k, "--go", "--writes-memory", "--firmware-shown", FIRMWARE]
        clear = last_result_sha()
        if clear:
            cmd += ["--clear-result", clear]
        rc = subprocess.run(cmd).returncode
        which, f = step_outcome()
        if rc or which != k or not f or not f.get("ok"):
            say()
            say("STOPPED at step %d (%s): %s" % (n, k, "the session did not finish" if rc or which != k or not f else "outcome " + f["outcome"]))
            say("Steps before it are %s. To be sure of the camera's state: cold boot it (battery out for 10 seconds)." % ("applied" if applying else "put back"))
            say("Please send the newest folders in camera_private.")
            raise SystemExit(1)
    say()
    say("All %d steps passed (%s)." % (len(steps), a.what))
    if applying and a.what == "apply":
        if a.no_meta:
            say("The files' MP4 headers say 3840x2160 (--no-meta): editors may open them squeezed; a remux to 3840x2560 fixes that.")
        else:
            say("The files' MP4 headers (tkhd, stsd, Sony's PROF) now say 3840x2560: editors should open them at 3:2 without a remux.")
            say("  Sony's XML (in the file and the sidecar) still says 3840x2160, 16:9.")
        say("DO NOT PLAY CLIPS BACK ON THE CAMERA while it is applied: the FX30 opens playback at 4096x2160 like the FX3, where an open-gate")
        say("  clip showed 'unable to display' and a second try froze the camera until the battery was pulled. Check the clips on a computer.")
        say("  (The optional, untested playback step is meant to fix this: fx30_apply.py playback / playback_fix_apply.)")
    if with_screen and a.what in ("apply", "screen"):
        say("The screen step: in Movie the rear screen should now show the whole picture at 3:2. On a 4:3 screen (what the FX30's")
        say("  2.36M-dot panel is expected to be: 1024x768) there are thin black bars above and below; on a 3:2 screen it fills it. A circle should look round.")
        say("  De-Squeeze Display (MENU > Setup > Display Option > De-Squeeze Display) now de-squeezes the 3:2 picture:")
        say("  1.3x shows 1.95:1, 1.5x 2.25:1, 1.6x 2.475:1, 2.0x 3:1 (the whole frame; the stock centre crop is off). The file does not change.")
        say("  While it is applied every 16:9 picture is shown as if it were this 3:2 picture (other movie formats look wrong on the screen).")
        say("  Please report: the screen with De-Squeeze Display Off and at each factor (a photo of something round helps), and the focus frames.")
    if a.what == "playback":
        say("The camera's playback decoder now opens the A7 IV's 7690x4320 channel (the one the A7 IV plays 3840x2560 clips with).")
        say("Please test, in this order, and write down what each does:")
        say("  1. Unplug USB. Press the playback button and open an ordinary clip (16:9, e.g. 4K or HD, recorded without the open-gate state).")
        say("  2. Then ONE open-gate 3840x2560 clip. If it says 'Unable to display': do NOT try again (a retry froze an FX3 before);")
        say("     leave playback and report. If the camera freezes or restarts: pull the battery for 10 seconds.")
        say("  3. If it plays: does it show the whole 3:2 frame, and does it play to the end?")
        say("Then send the newest folders in camera_private. To put it back: playback-putback, or battery out for 10 seconds.")
    elif a.what == "playback-putback":
        say("The playback decoder is stock again (4096x2160).")
    if closing:
        if a.no_movie_session:
            say(">>> BEFORE you unplug: set %s. Then unplug USB." % MOVIE)
        else:
            movie_session()
        say()
        say("Use only XAVC HS 4K or XAVC S 4K at 24p (23.98p), or 25p on a PAL camera, while it is applied. 30p (and 24.00p on a PAL camera)")
        say("  read the tall window too, but their encoder is not set up: do not record them. Do not use 60p, 120p, S&Q or Proxy Recording.")
        say("If the camera stops or restarts: do NOT pull the battery yet. Choose a still mode, replug USB and run dump_info, then send camera_private.")
        say("To return to stock: battery out for 10 seconds.")


if __name__ == "__main__":
    main()
