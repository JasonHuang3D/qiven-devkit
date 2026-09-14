@echo off
setlocal EnableExtensions EnableDelayedExpansion

call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1

set "ESC="
set "CYAN="
set "GREEN="
set "RED="
set "YELLOW="
set "RESET="
if not defined QIVEN_TEST_NO_COLOR if not defined NO_COLOR if not defined CI (
    for /F "delims=#" %%E in ('"prompt #$E# & for %%B in (1) do rem"') do set "ESC=%%E"
    if defined ESC (
        set "CYAN=!ESC![36m"
        set "GREEN=!ESC![32m"
        set "RED=!ESC![31m"
        set "YELLOW=!ESC![33m"
        set "RESET=!ESC![0m"
    )
)

set "TAG_RUN=!CYAN![ RUN]!RESET!"
set "TAG_OK=!GREEN![ OK ]!RESET!"
set "TAG_FAIL=!RED![FAIL]!RESET!"
set "TAG_WAIT=!YELLOW![WAIT]!RESET!"

set "REPO_ROOT=%~dp0.."
set "HEAD_SHA=unknown"
for /F %%H in ('git -C "%REPO_ROOT%" rev-parse HEAD 2^>nul') do set "HEAD_SHA=%%H"

set "LOG_ROOT=%TEMP%\qiven-devkit-tests-%RANDOM%-%RANDOM%"
mkdir "%LOG_ROOT%" >nul 2>nul
if errorlevel 1 (
    echo !TAG_FAIL! Could not create test log directory: %LOG_ROOT%
    exit /b 1
)

set /a FAILURES=0
set "STATUS_CMD=NOT-RUN"
set "STATUS_MISSING=NOT-RUN"
set "STATUS_REGRESSION=NOT-RUN"

echo !TAG_RUN! qiven-devkit test suites
echo        HEAD: !HEAD_SHA!
echo        Passing-suite logs are buffered. Set QIVEN_TEST_VERBOSE=1 to print them.
echo.

echo !TAG_RUN! cmd-control-flow
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%REPO_ROOT%" -P "%~dp0cmd-control-flow-test.cmake" >"%LOG_ROOT%\cmd-control-flow.log" 2>&1
if errorlevel 1 (
    set "STATUS_CMD=FAIL"
    set /a FAILURES+=1
    echo !TAG_FAIL! cmd-control-flow
) else (
    set "STATUS_CMD=PASS"
    echo !TAG_OK! cmd-control-flow
)

echo !TAG_RUN! adoption-missing-sync
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%REPO_ROOT%" -P "%~dp0adoption-missing-sync-test.cmake" >"%LOG_ROOT%\adoption-missing-sync.log" 2>&1
if errorlevel 1 (
    set "STATUS_MISSING=FAIL"
    set /a FAILURES+=1
    echo !TAG_FAIL! adoption-missing-sync
) else (
    set "STATUS_MISSING=PASS"
    echo !TAG_OK! adoption-missing-sync
)

echo !TAG_RUN! devkit-regression
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%REPO_ROOT%" -DQIVEN_TOOLCHAIN_ROOT_TEST="%QIVEN_TOOLCHAIN_ROOT%" -P "%~dp0test.cmake" >"%LOG_ROOT%\devkit-regression.log" 2>&1
if errorlevel 1 (
    set "STATUS_REGRESSION=FAIL"
    set /a FAILURES+=1
    echo !TAG_FAIL! devkit-regression
) else (
    set "STATUS_REGRESSION=PASS"
    echo !TAG_OK! devkit-regression
)

echo.
echo === TEST SUMMARY ===
call :print_summary "cmd-control-flow" "!STATUS_CMD!"
call :print_summary "adoption-missing-sync" "!STATUS_MISSING!"
call :print_summary "devkit-regression" "!STATUS_REGRESSION!"

if !FAILURES! GTR 0 (
    echo.
    echo === FAILED SUITE LOGS ===
    if "!STATUS_CMD!"=="FAIL" call :print_log "cmd-control-flow" "%LOG_ROOT%\cmd-control-flow.log"
    if "!STATUS_MISSING!"=="FAIL" call :print_log "adoption-missing-sync" "%LOG_ROOT%\adoption-missing-sync.log"
    if "!STATUS_REGRESSION!"=="FAIL" call :print_log "devkit-regression" "%LOG_ROOT%\devkit-regression.log"
) else if /I "%QIVEN_TEST_VERBOSE%"=="1" (
    echo.
    echo === VERBOSE SUITE LOGS ===
    call :print_log "cmd-control-flow" "%LOG_ROOT%\cmd-control-flow.log"
    call :print_log "adoption-missing-sync" "%LOG_ROOT%\adoption-missing-sync.log"
    call :print_log "devkit-regression" "%LOG_ROOT%\devkit-regression.log"
)

echo.
if !FAILURES! GTR 0 (
    echo !TAG_FAIL! Test suites complete: failures=!FAILURES!
    rd /s /q "%LOG_ROOT%" >nul 2>nul
    exit /b 1
)

echo !TAG_OK! Test suites complete: failures=0
rd /s /q "%LOG_ROOT%" >nul 2>nul
exit /b 0

:print_summary
if "%~2"=="PASS" (
    echo !TAG_OK! %-24~1 %~2
) else (
    echo !TAG_FAIL! %-24~1 %~2
)
exit /b 0

:print_log
echo.
echo !TAG_FAIL! %~1 detailed output
echo ------------------------------------------------------------------------
type "%~2"
echo ------------------------------------------------------------------------
exit /b 0
