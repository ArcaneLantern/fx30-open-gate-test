@echo off
rem FX30 (firmware 6.01): 5.7K, NOT RUN ON ANY FX30: a real 5760x3840 file of the same 5952x3968 sensor window, in XAVC S 4K at 24p (25p on PAL), about 300 Mbps on the 100M record settings, I and P pictures only (no B frames), MP4 headers at 5760x3840 (four steps from a cold boot, then one read-only session).
rem WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx30_apply.py" apply --57 %*
echo.
pause
