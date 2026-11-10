@echo off
setlocal DisableDelayedExpansion
"%~dp0adb-speaker.exe" stream
set "stream_status=%errorlevel%"
if not "%stream_status%"=="0" pause
exit /b %stream_status%
