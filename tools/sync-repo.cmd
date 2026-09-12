@echo off
setlocal
if "%~1"=="" (
    echo Usage: %~nx0 REPOSITORY
    exit /b 2
)
call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%~dp0.." -DREPOSITORY="%~1" -P "%~dp0..\cmake\QivenRepoSync.cmake"
exit /b %errorlevel%
