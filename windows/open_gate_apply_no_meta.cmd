@echo off
rem FX30 (firmware 6.01): apply the open-gate state with the encoder step without the MP4 header heights: the files' MP4 headers keep saying 3840x2160.
rem WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx30_apply.py" apply --no-meta %*
echo.
pause
