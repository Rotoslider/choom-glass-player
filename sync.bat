@echo off
rem Copy the glass from home (start tools\share_glass.py on the home glass first).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe player\sync.py %*) else (py -3 player\sync.py %*)
pause
