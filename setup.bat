@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --no-deps --no-build-isolation -e .
if errorlevel 1 exit /b 1
echo Ready. Run start.bat to open Image Factory.
pause
