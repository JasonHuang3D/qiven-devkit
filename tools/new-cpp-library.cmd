@echo off
setlocal
if "%~7"=="" goto :usage
call "%~dp0resolve-toolchain.cmd"
if errorlevel 1 exit /b 1
set "SOLUTION=%~8"
if not defined SOLUTION set "SOLUTION=%~2"
"%QIVEN_CMAKE%" -DDEVKIT_ROOT="%~dp0.." -DTEMPLATE_KIND="cpp-library" -DDESTINATION="%~1" -DREPOSITORY_NAME="%~2" -DCMAKE_PROJECT_NAME="%~3" -DCMAKE_TARGET_NAME="%~4" -DCMAKE_ALIAS="%~5" -DCPP_NAMESPACE="%~6" -DTEST_OPTION_NAME="%~7" -DVS_SOLUTION_NAME="%SOLUTION%" -P "%~dp0..\cmake\QivenRepoNew.cmake"
exit /b %errorlevel%
:usage
echo Usage: %~nx0 DEST REPOSITORY PROJECT TARGET ALIAS NAMESPACE TEST_OPTION [SOLUTION]
exit /b 2
