@echo off
rem Mittler: make one video as high quality as the master export (pyengine\mittler\enhance.py).
rem   enhance.cmd <input video> [<output.mp4>] [--upscale anime^|real^|none]
rem Python: %MITTLER_PYTHON% -> python on PATH (needs numpy, opencv, Pillow: the render python).
rem ffmpeg: %MITTLER_FFMPEG_DIR% -> PATH. Tools: %MITTLER_ESRGAN% / %MITTLER_RIFE% (or --esrgan / --rife).
rem Old names (compatibility): %CC_PYTHON% / %CC_FFMPEG_DIR% are read here when the MITTLER_ ones are not set; CC_ESRGAN / CC_RIFE are read by enhance.py.
rem Keep this file ASCII only (cmd.exe reads it in the OEM code page).
setlocal
set "PY=%MITTLER_PYTHON%"
if not defined PY set "PY=%CC_PYTHON%"
if not defined PY set "PY=python"
set "FFDIR=%MITTLER_FFMPEG_DIR%"
if not defined FFDIR set "FFDIR=%CC_FFMPEG_DIR%"
if defined FFDIR set "PATH=%FFDIR%;%PATH%"
set "PYTHONPATH=%~dp0..\pyengine;%PYTHONPATH%"
"%PY%" -X utf8 -m mittler enhance %*
exit /b %ERRORLEVEL%
