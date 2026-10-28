@echo off
rem Start the travel glass: the server, the mic and Chrome on the Portrait. Close this window to stop it.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe player\launch.py) else (py -3 player\launch.py)
pause
