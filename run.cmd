@echo off
REM Wrapper so you don't have to activate the venv each time.
REM Usage: run.cmd <command> [args...]   e.g.  run.cmd run --platform naukri
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" %*
