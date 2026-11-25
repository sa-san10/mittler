@echo off
rem Old name (claude-cut) kept for compatibility: the tool is now mittler.cmd in the same folder (renamed 2026-11-12).
rem Projects, skills and notes written before the rename call "tools\cc.cmd serve ..." / "tools\cc.cmd node ...". This only forwards to mittler.cmd.
rem Keep this file ASCII only (cmd.exe reads it in the OEM code page).
call "%~dp0mittler.cmd" %*
exit /b %ERRORLEVEL%
