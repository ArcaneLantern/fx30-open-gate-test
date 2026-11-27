@echo off
rem FX30 (firmware 6.01): NEW, NOT RUN ON ANY CAMERA: turn off the camera's card-speed check (the V90 rule for XAVC S-I, V60 for 200 Mbps, V30, Class 10, CFexpress VPG), e.g. for an NVMe drive in a CFexpress Type A adapter. Two instructions of libmpr.so in memory. After it: take the card out and put it back. Independent of the open-gate steps.
rem WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx30_apply.py" cardspeed %*
echo.
pause
