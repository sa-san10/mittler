@echo off
rem Mittler: run with the Node runtime bundled in VS Code (Electron as Node). No separate Node install needed.
rem   mittler.cmd serve <timeline.cut.json> [--port N] [--render-python PY] [--ffmpeg-dir DIR] [... any number of options]   (renders on this PC)
rem   mittler.cmd node <script.js> [... any number of arguments]
rem The old name cc.cmd (same folder) still works: it only calls this file.
rem Keep this file ASCII only (cmd.exe reads it in the OEM code page).
rem 2026-11-12: all arguments are passed on, and the exit code of Node is returned.
rem 2026-11-15: the arguments go to Node unchanged (%*); tools\mittler_launch.js picks serve/node. This file does not look at them one by one any more:
rem an argument with spaces from bash (--title "Kuro Coffee" arrives as \"Kuro Coffee\") used to break the old "if %~2" loop
rem ("Coffee\""=="" was unexpected at this time."). Arguments are no longer split at = , ; either.
setlocal
set "CODE_EXE=%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
if not exist "%CODE_EXE%" (echo VS Code not found: %CODE_EXE% & exit /b 1)
set ELECTRON_RUN_AS_NODE=1
"%CODE_EXE%" "%~dp0mittler_launch.js" %*
exit /b %ERRORLEVEL%
