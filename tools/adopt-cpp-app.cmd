@echo off
setlocal
if "%~8"=="" goto :usage
if not "%~1"=="check" if not "%~1"=="apply" goto :usage
call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1
set "SOLUTION=%~9"
if not defined SOLUTION set "SOLUTION=%~3"
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%~dp0.." -DTEMPLATE_KIND="cpp-app" -DMODE="%~1" -DREPOSITORY="%~2" -DREPOSITORY_NAME="%~3" -DCMAKE_PROJECT_NAME="%~4" -DCMAKE_TARGET_NAME="%~5" -DCMAKE_ALIAS="%~6" -DCPP_NAMESPACE="%~7" -DTEST_OPTION_NAME="%~8" -DVS_SOLUTION_NAME="%SOLUTION%" -P "%~dp0..\cmake\QivenRepoAdopt.cmake"
exit /b %errorlevel%
:usage
echo Usage: %~nx0 MODE REPOSITORY REPOSITORY_NAME PROJECT TARGET ALIAS NAMESPACE TEST_OPTION [SOLUTION]
echo MODE must be exactly check or apply.
exit /b 2
