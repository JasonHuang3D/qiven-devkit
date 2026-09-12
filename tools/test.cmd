@echo off
setlocal
call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%~dp0.." -DQIVEN_TOOLCHAIN_ROOT_TEST="%QIVEN_TOOLCHAIN_ROOT%" -P "%~dp0test.cmake"
exit /b %errorlevel%
