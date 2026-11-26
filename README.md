# FX30 open gate: test kit (firmware 6.01)

<p><b>Kit v2 (2026-11-26). v2 has not run on a camera yet.</b> Kit v1 ran on three FX30s and did not work: the cause is found and fixed here (see "What v1 got wrong"). The kit brings the open gate that works on the A7 IV, A7S III and FX3 to the Sony FX30 (ILME-FX30) firmware 6.01. It is meant to record a true 3840 × 2560 picture of the 3:2 area of the FX30's 6K read-out, in XAVC S 4K and XAVC HS 4K at 23.98p (25p on a PAL camera), with MP4 headers that say 3840 × 2560. It also shows the whole picture at 3:2 on the rear screen and sets the FX30's own De-Squeeze Display for it. The patch only writes to the camera's memory: a battery pull removes it.</p>

**What v1 got wrong.** On three cameras (NTSC and PAL) every step applied, the camera kept working and the file was 3840 × 2560, but:

- the picture filled only the top 2160 of the 2560 rows, with black below;
- the colours shifted, mostly towards blue, and dark levels were crushed.

The cause, read from a tester's dump and confirmed in the firmware: the FX30 sets the sensor window in **two** places. One is the set of tables and records that tell the image processor what the sensor sends; v1 changed those. The other is seven registers of the sensor itself, which v1 did not change, because I had read the table that holds them (the "register matrix") from the wrong start and missed its first 15 rows. So the sensor kept sending 3348 rows while everything after it expected 3968. That gives exactly the black band (3348 of 3968 rows = 2160 of 2560), and the colour fault follows from the lead-in rows, phase-detect rows and black reference being read in the wrong places.

**What v2 changes.**

- **The sensor's seven window registers are written too** (first row, number of line pairs, the phase-detect rows, the lead-in).
- **The window starts at row 94, not 96.** Every stock window of this sensor mode starts at a row that is 2 more than a multiple of 4; v2 keeps that.
- **The debug dump now reads what the sensor is programmed for** and says plainly whether it agrees with the records. v1's dump could not show this fault.
- **A second sensor variant, B, for an A/B test** (see "Variant B"): the same design with the two values another tester reported clean colour with. A is the default.
- A program file left on the camera by a cut-off session (of v1 or v2) is removed automatically at the next run.
- Harmless lines (`read failed -21`, `truncated at 2048 bytes`) no longer count as problems.

**Where it stands:**

- **Built and emulated; v2 not run.** Every step is built from the FX30 6.01 firmware's own tables and checked against the FX30's own code in emulation. New for v2: the firmware's own routine that sends the sensor its registers was run in emulation with the new values, and the tester's real v1 dumps were replayed through the new dump reader, which flags v1's fault on them (`PORT_NOTES.md`).
- **How it works on the FX30.** In 4K the FX30 reads a 5952 × 3348 window of its sensor ("6K") and scales it to 4K. The kit keeps the 4K mode's own sensor mode and line timing and only makes the window taller, in the sensor's registers and in the tables that describe it:

  | | Stock 4K | This kit |
  |---|---|---|
  | Sensor window | 5952 × 3348 (16:9) from row 406 | **5952 × 3968 (3:2) from row 94** |
  | Share of the sensor (6192 × 4128) | 96% × 81% | **96% × 96%** |
  | Line pairs the sensor reads per frame | 1,680 | 1,990 (of 4,410 line periods in a 24p frame) |
  | File | 3840 × 2160 | **3840 × 2560** |

  The taller picture is squeezed into the stock first-stage picture and stretched back to 3:2 at the end, the A7 IV's proven method (on the FX30 the scaler's own code was emulated with it and keeps every row).
- **The shape of the kit is the FX3 kit's** (`fx3-open-gate-test`, which records open gate on two FX3s): the same launchers, the read-only check before any write, the closing read-only session, Windows, macOS and Android. Its encoder, MP4-header, screen and playback steps are the FX3 kit's at the FX30's addresses (the FX30's main-processor software is the FX3's, moved). No raw-write-buffer step is needed: the FX30's stock buffer already holds the taller picture.

**Kits cannot be mixed up.** The FX3, FX2, ZV-E1 and A7S III kits' check libraries say NOT READY on an FX30, and their write steps write nothing on one. This kit's check says NOT READY on an FX3, FX2 or A7 IV. Every write step writes nothing unless each byte it changes holds exactly the FX30 6.01 stock value. All of this was checked in emulation.

| Launcher | What it does | Writes to the camera? |
|---|---|---|
| `check_readonly.cmd` | Confirms the camera runs the 6.01 software the port was made from and reads what every patch site holds. Verdict READY / NOT READY | No |
| `dump_info.cmd` | **The debug dump for testers.** The same as the check, plus: memory map, the camera's own logs (kernel and image processor), **the window the sensor is programmed for and whether it agrees with the stored mode records**, the scaler's state, the display (panel type, 3:2 ratio, frame tables, de-squeeze words) | No |
| `open_gate_apply.cmd` | Applies open gate in four steps: sensor, output size, encoder (with the MP4 headers), then the rear screen at 3:2 with De-Squeeze Display set for it. Ends with one read-only dump | **Yes: memory only** |
| `open_gate_apply_no_screen.cmd` | Only the three open-gate steps | **Yes: memory only** |
| `open_gate_apply_no_meta.cmd` | Open gate with the encoder step that leaves the MP4 headers at 3840 × 2160 | **Yes: memory only** |
| `open_gate_apply_variant_b.cmd` | **A/B test:** the apply with the sensor step's variant B. Only if the default gives a full picture with wrong colour | **Yes: memory only** |
| `open_gate_switch_to_b.cmd` | **A/B test:** after a normal apply in the same power-on, changes only the sensor step to variant B | **Yes: memory only** |
| `open_gate_switch_to_a.cmd` | **A/B test:** changes the sensor step back from variant B to the default | **Yes: memory only** |
| `open_gate_putback.cmd` | Puts the four steps back (it finds which sensor variant is in memory) | Yes: memory only |
| `screen_putback.cmd` | Puts the screen step back | Yes: memory only |
| `playback_fix_apply.cmd` | **Optional, not run on any camera** (the FX3's own was not run either): lets the camera play 3840 × 2560 clips back (see "While it is applied") | **Yes: memory only** |
| `playback_fix_putback.cmd` | Puts the playback step back | Yes: memory only |

Nothing in this kit writes to the camera's firmware or to its settings.

## Before you start

1. The camera's menu must show **Ver. 6.01**. On any other version, stop and tell us the version.
2. **USB Connection Mode: Mass Storage.**
3. A charged battery. Do not record or play back while a step runs.
4. **Modes.** The FX30 has no mode dial: press **MODE**, turn the control wheel to the mode, press its centre. Below, "STILL" means a still-image mode (Program Auto, Aperture or Shutter Priority, Manual Exposure) and "MOVIE" means Movie.

## Windows, once

1. Install Python 3.10 or later from python.org (with the "py launcher").
2. Run `windows/setup.cmd`.
3. Install the libusb-win32 driver for the camera with [Zadig](https://zadig.akeo.ie): Options, List All Devices, pick the camera, choose libusb-win32, Replace Driver. The first run switches the camera to service mode, where it shows up as a new device (054C:0336 on the other bodies): install the driver for that one too, then run the step again.

## macOS, once (not run with an FX30 yet)

The macOS kit is the A7 IV kit's macOS port, carried over unchanged apart from the launcher names. It runs the same scripts as Windows (`windows/tools`).

1. Python 3.9 or later: the one macOS offers with the Xcode Command Line Tools (run `xcode-select --install` in Terminal) works, or install it from python.org.
2. Double-click `macos/setup.command`. It sets up Python and the USB library the scripts use. No Homebrew and no driver are needed.
3. Each Windows launcher has a macOS twin with the same name (`macos/check_readonly.command`, `dump_info.command`, `open_gate_apply.command`, and so on). Everything below that says `.cmd` works the same with the `.command` file.

Each live run asks for your Mac password: macOS keeps its own driver on the camera's USB connection, and only an administrator can hand the camera over to the script. The script unmounts the camera's memory card first; it does not erase anything on it. The results go to the same `windows/camera_private` folder.

If macOS refuses to open a .command file ("unidentified developer" or "could not verify"), open System Settings > Privacy & Security, scroll down and click "Open Anyway". Or open Terminal, type `bash` and a space, drag the .command file into the window, and press Return.

## Android (app 0.3; v1's app ran the steps on a phone, v2's has not run yet)

`android/FX30-OpenGate.apk` runs this kit from a phone connected to the camera by USB-C (or an OTG adapter). It carries exactly the files in `windows/tools` of this commit and runs them unchanged; only the USB access, the dialogs and the folder for the results are the phone's.

1. Install the APK (allow installing from unknown sources). It installs beside the other kits' apps; they do not share anything on the phone.
2. Set the camera as for the PC (below), and also **USB Power Supply: Off**, or it charges from the phone.
3. **1. Read-only check** first: the apply starts only after a check on this phone said READY. Then **2. Apply to camera**. The "Screen step" box chooses between the four-step apply (ticked) and the three open-gate steps only. Leave the "Sensor variant B" box unticked unless you are doing the A/B test below; **Put back** works for either variant. **Dump info** is the debug dump.
4. When Android asks to open *FX30 Open Gate* for the camera, tick **Always** and press OK. It comes up twice: once in Mass Storage, once in service mode.
5. When the log says **unplug and plug in again**, do that with the phone cable. Never switch the camera off.
6. **Stop waiting** ends a wait for the camera. It never interrupts a step that is talking to the camera.
7. Afterwards, **Export logs** writes a zip to `Download/FX30-OpenGate/` on the phone: send that zip back.

**Self-test** and **Dry run** need no camera and send nothing.

## The read-only steps (check and debug dump)

Each launcher asks for the firmware version the menu shows. Each run makes a new folder in `windows/camera_private`: the report (`fx30_report.txt`), the raw result, and for a dump the coprocessor pages it copied (`cp_*.bin`).

- **Check or dump in the stills state:** set STILL, connect, run the launcher.
- **Dump of the 4K state:** set File Format XAVC S 4K (or XAVC HS 4K) at 24p, S&Q off. Set MOVIE, record a few seconds, stop. **Stay in MOVIE**, connect, run `dump_info.cmd`.

What they do to the camera: they switch it to service mode, write one small program file to the service partition, which the camera loads once, and delete that file again in the same session. The program only reads and creates one file, its report, on the camera's RAM disk. Its source is `windows/tools/camera_tests/CT6_memory_read_check/helper_fx30/fx30read.c`.

## The write steps

**What they change.** Four groups of bytes in the running camera's memory, one per step:

1. **Sensor** (`ogsq_fx30_v2`): in the five 4K 16:9 drive modes (24p, 25p, 30p, each also in its longer-line variant), the sensor window 5952 × 3968 from row 94 instead of 5952 × 3348 from row 406:
   - **seven sensor registers** in the register matrix (new in v2): first row, line pairs, first phase-detect block, phase-detect rows, lead-in;
   - 9 table cells per mode that describe the same window to the image processor;
   - the two 4K picture records (first stage 5976 × 3976, squeezed into the stock 4336 × 2438 picture);
   - 24 bytes of each mode's stored record, with the vertical ratio 27/32 that makes the scaler keep every row. The camera computes those records at start-up from its NTSC or PAL table; the step finds which and writes the matching values. The table and register values are the same on NTSC and PAL cameras.

   The sensor gets its registers when the camera sets the movie mode, so enter MOVIE after the apply, not before.
2. **Output size** (one word): 3840 × 2160 becomes 3840 × 2560.
3. **Encoder** (101 + 6 sites): the encoder's tables for XAVC HS 4K and XAVC S 4K at 23.98p and 25p, and the two height values the MP4 writer puts in the file's headers, 2160 → 2560. `open_gate_apply_no_meta.cmd` leaves the headers at 2160.
4. **Screen** (30 words):
   - a 16:9 live view is shown at the 3:2 shape (it holds the whole 3:2 picture squeezed);
   - the focus and tracking frames are told where the picture now is;
   - De-Squeeze Display's shapes are set for the 3:2 picture (below).

Each step first checks that every byte it is about to change holds its stock value, writes, reads back, and undoes its own writes if anything does not match. `open_gate_apply_no_screen.cmd` runs only the first three.

**De-Squeeze Display** (Sony's own feature, MENU > Setup > Display Option > De-Squeeze Display). The camera works out each shape for a 16:9 picture. With the open-gate picture, which is 3:2, every shape would be about 18% off, so step 4 gives it the shapes of the 3:2 frame:

| Setting | Stock FX30, 16:9 picture | With this kit, the 3:2 open-gate picture |
|---|---|---|
| 1.3x | 2.31:1 | **1.95:1** |
| 1.5x | 2.67:1 | **2.25:1** |
| 1.6x | 2.93:1 | **2.475:1** |
| 2.0x | 2.67:1 (the centre 4:3 of the frame) | **3:1: the whole frame** (the centre crop is turned off) |

It changes only the preview, not the recorded file.

**What we do not know yet.**

- **Whether the sensor accepts the taller window.** v1 never asked it (its registers stayed stock), so this is still the first real test. No stock FX30 movie mode reads more than 1,680 line pairs at this speed; the full height is read only by the stills modes, at a slower line rate. The register values follow rules that all four stock windows of this sensor mode obey, read from the firmware (`PORT_NOTES.md`). If the sensor or its link refuses, expect a broken picture or a restart when MOVIE starts, not lasting harm: a battery pull clears it.
- **Whether the colour is right once sensor and picture side agree.** I expect so, because the mismatch that caused it is removed, but only a camera can show it.
- **The phase-detect rows** (autofocus). The window carries 82 rows of phase-detect data instead of 68. If the count is wrong, autofocus may misbehave or the picture may break.
- **XAVC HS.** Under v1 one camera restarted when File Format was changed to XAVC HS with the patch applied. The cause is not known. Test XAVC S first.
- **The power switch.** On the A7 IV switching off and on keeps the patch; on the A7S III it removes it. Not known on the FX30: keep it switched on during the apply.
- **The rear panel** is 4:3 (type 2, read on three cameras; 2,359,296 dots = 1024 × 768), so the 3:2 picture has thin black bars above and below.
- **Exposure, autofocus, rolling shutter, long recordings, heat:** the sensor reads 18.5% more rows per frame, so rolling shutter grows by about the same.

**While it is applied**

- Record **XAVC S 4K at 24p (23.98p), or 25p on a PAL camera** first. Try **XAVC HS 4K** only after an XAVC S clip is good, and tell us what it does. 30p (and 24.00p on a PAL camera) read the tall window too, but their encoder is not set up: do not record them. 60p, 120p, S&Q, HD formats and Proxy Recording are not set up and are likely to fail.
- On the rear screen every 16:9 picture takes the 3:2 shape, and De-Squeeze Display uses the 3:2 shapes, so other movie formats look wrong there. HDMI output is not part of this kit and has not been checked.
- **Do not play clips back on the camera.** Like the FX3, the FX30 opens every movie playback at 4096 × 2160; on two FX3s an open-gate clip showed "Unable to display" and a second try froze the camera until the battery was pulled. Check the clips on a computer. The optional playback step (`playback_fix_apply.cmd`, below) is meant to fix this and has not run on any camera.

**How to run it**

If kit v1 is still applied, pull the battery for 10 seconds first.

1. In the menu, set File Format **XAVC S 4K** and 24p (25p on a PAL camera). S&Q off. De-Squeeze Display Off for now. Proxy Recording Off.
2. **A stock baseline (new, one minute):** set MOVIE, record a few seconds, stop, stay in MOVIE, connect USB and run `windows/dump_info.cmd`. This shows the stock sensor state in movie mode, which v1's dumps did not capture.
3. Set STILL. Then pull the battery for 10 seconds and switch on, so that nothing of an earlier run is left. Do not go to MOVIE yet.
4. Connect USB and run `windows/check_readonly.cmd`. It must say VERDICT READY.
5. Run `windows/open_gate_apply.cmd`. It starts only if your newest saved check or dump says READY. It asks for the firmware version and for a typed YES.
6. It runs four steps. Between steps it asks you to **unplug and replug the USB cable. Do not switch the camera off and do not pull the battery** until the script says it is finished.
7. After the four steps the script asks for one more session, which only reads. **Unplug USB, set MOVIE, look at the screen for five seconds, and plug in again.** The script then runs the debug dump by itself and prints:
   - the window the stored record describes (expected: 3968 rows from row 94);
   - the window the **sensor** is programmed for (expected: the same), and **AGREE** or **DO NOT AGREE**;
   - the rear panel's type.

   If it says DO NOT AGREE, send the folder and stop there: recordings will not be right.
8. When it says so, unplug. The rear screen should show the whole picture at 3:2. If it first shows a 16:9 layout with a bar at the bottom, open and close MENU once (seen under v1).
9. Record 10 to 30 seconds in XAVC S 4K and stop. Set MOVIE again if needed, connect USB and run `windows/dump_info.cmd` once more. Check the clip on a computer.
10. Only if that clip is good: try XAVC HS 4K, then De-Squeeze Display at 1.3x and 2.0x.
11. To return to stock: battery out for 10 seconds, or `open_gate_putback.cmd`.

**Variant B (an A/B test of the sensor step)**

The default sensor step is variant **A**. Variant **B** is the same design with two values changed, the ones a tester reported clean colour with in issue 1:

| | A (default) | B |
|---|---|---|
| First phase-detect row told to the image processor | 121 (the rule every stock mode obeys) | 145 (window row + 51, as in the stock 4K mode) |
| Read-out length | 2,014 line periods (stock rule) | 2,020 |
| Sensor registers, picture records, every other step | the same | the same |

I do not know that B is right; it does not follow the firmware's own rule. It is there so that one session can answer the question.

- **Use A first.** If A gives a full 2560-row picture with right colours, there is nothing to switch.
- **If A gives a full picture but wrong colours** (the closing dump said AGREE): set STILL, run `open_gate_switch_to_b.cmd` (two steps, then the read-only session in MOVIE), record again and compare. `open_gate_switch_to_a.cmd` goes back.
- **If A does not give a full picture,** B will not help: the sensor registers are the same in both. Send the dumps.
- Reports show which variant is in memory (`sensor design in memory: A` or `B`). Please say which variant each clip was recorded with.

**If the camera restarts by itself** at any point: do not pull the battery. Set STILL, connect USB, run `windows/dump_info.cmd`, and only then pull the battery for 10 seconds. The image processor keeps its own log across a restart without power loss, and the dump reads it.

**Please send back**

- The zipped `windows/camera_private` folder, with the stock movie baseline, the closing dump of the apply and the dump after recording in it.
- One frame of the clip (or the clip): does the picture fill all 2560 rows, and are the colours right?
- What the rear screen showed in MOVIE before recording: the whole 3:2 picture, or lines, wrong colours, black parts, flicker.
- The clip, or its properties: size, frame rate, codec. Do the same with XAVC S 4K if you can.
  - **Field of view:** a still photo of the same scene from a tripod, so we can see how much of the sensor height the clip has (expected: 96% of the photo's width and height, centred).
  - **MediaInfo:** `mediainfo --Output="Video;%Width%x%Height% original %Width_Original%x%Height_Original%" FILE` should give 3840x2560 with no "original" size. ffprobe cannot show the header change: it reads the size from the stream.
  - **Editors:** whether Resolve or Premiere opens the original file at 3:2.
- Autofocus: does it find and hold focus on a subject near the top or bottom of the 3:2 frame?
- The rear screen with De-Squeeze Display Off, 1.3x and 2.0x: a phone photo with something round in the picture helps.
- Whether the focus and tracking frames sit on the subject with De-Squeeze Display Off.
- **One check after a power-off.** When you are done: switch the camera off and on with the power switch (no battery pull), set STILL, run `windows/check_readonly.cmd`, and include that folder. It tells us whether the power switch removes the patch on the FX30.
- Your settings: file format and record setting, frame rate, NTSC or PAL, base ISO (Cine EI or Log), SteadyShot.

**If the camera misbehaves** (grey lines, flicker, restart, freeze, recording that stops by itself): do not pull the battery straight away if the camera still responds. Set STILL, connect USB, run `dump_info.cmd`, and send the folder. Then pull the battery for 10 seconds. If the camera does not respond at all, just pull the battery. `open_gate_apply_no_screen.cmd` applies open gate without the screen step.

**If the apply stops part-way:** it says at which step. Pull the battery for 10 seconds to be sure of the camera's state, and send the folder.

**To remove only the screen step:** set STILL and run `windows/screen_putback.cmd`.

**The optional playback step** (`playback_fix_apply.cmd`, after an apply or on its own; NOT RUN ON ANY CAMERA): it makes the camera open playback with the A7 IV's 7690 × 4320 channel, which the A7 IV uses to play the same clips. It changes four instructions and one table word of the camera's AV program; its library refuses unless the processors' caches can be made to fetch the new instructions. Then: open an ordinary 16:9 clip first, then ONE open-gate clip. If it says "Unable to display", do not try again: leave playback and report. `playback_fix_putback.cmd` or a battery pull removes it.

## Questions from the first runs

- **Do PAL and NTSC need different values?** No. The sensor registers and table values are the same. Only some time values inside the stored mode records differ, and the sensor step detects which set the camera holds and writes the matching one.
- **`read failed -21` (ten per write step).** The program tries to read the entries of `/proc/driver/pcie` as files, and some are directories. Harmless; now listed as notes.
- **`truncated at 2048 bytes` (two per dump, also on a stock camera).** A `/proc` file longer than the program's copy limit. Harmless; now listed as notes.
- **The values suggested in issue 1** (LC 147, read-out 2020) are not used. In the firmware that LC value is always 25 + 48 × the sensor's first phase-detect block, for every mode, never "window row + 51" (the DCI and Super 35 windows contradict that). The issue does not say whether that state also changed the sensor's registers. If it did not, the two values fitted the picture side to a sensor still on the stock window. If it did, they come from a state that worked. So they are carried as **variant B**, to be tried only if the default shows wrong colour. If you have a dump (`dump_info`) of a state with clean colour and a full picture, please send it: it shows the sensor's registers and settles this.

## If something stops

Every stop prints a reason and "Nothing was sent" or what was sent. Please send that text. Common ones:

- *the camera is in service mode but that device has no libusb driver yet*: expected on the first run. Do the Zadig step for the new device and run again.
- *DeviceInfo.xml is not the file of the 6.01 update*: another firmware or model. Nothing further is sent.
- *DIFFERS from the 6.01 update* in a check: not an FX30 on 6.01 (an FX3, FX2 or A7 IV gives this too). The apply will not start.
- *the stored records hold neither timing variant*: the camera's mode records are not what the 6.01 software computes. Nothing was written; send the folder.
- *a libJit.so is already on the service partition*: a session broke half-way. A file of this kit (v1 or v2) is now removed automatically at the next run. For a file of another kit, the message prints its SHA-256: run the read-only check with `--remove-library` and that value.

## What is in here

- `windows/`: the launchers, `setup.cmd`, and `tools/`:
  - the scripts, the pinned program files and their source;
  - the patch designs of every step;
  - the builders and emulations of the designs (`tools/modding/fx30`).
- `macos/`: `setup.command` and one `.command` launcher per Windows launcher; they run `windows/tools`.
- `android/FX30-OpenGate.apk`: the phone app, carrying `windows/tools` as published here.
- `PORT_NOTES.md`: how the open gate was built for the FX30, what was checked and how, the address map, and what is not known.

Built on [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) (vendored under `windows/tools/third_party`, MIT licence).
