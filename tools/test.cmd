@echo off
setlocal
call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%~dp0.." -P "%~dp0test.cmake"
exit /b %errorlevel%
