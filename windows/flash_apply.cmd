@echo off
rem FX30 (firmware 6.01): NEW, NOT RUN ON ANY CAMERA: an external flash with the electronic shutter (the ZV-E1's rule path, the flash menus, the flash shoe IDs; 17 places in the main application's memory). After it: Movie, then back to M, then fit the flash. Independent of the open-gate steps.
rem WRITES into the camera's memory (not firmware, not settings). A cold boot (battery out for 10 seconds) returns it to stock; whether the power switch alone does on the FX30 is not known.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing: run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\camera_tests\CT6_memory_read_check\fx30_apply.py" flash %*
echo.
pause
