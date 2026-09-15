cmake_minimum_required(VERSION 3.28)

if(NOT DEFINED DEVKIT_ROOT)
    get_filename_component(DEVKIT_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
endif()

set(cmd_templates
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/resolve-toolchain.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/format.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/format-check.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/gen-vs2022-x64.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/apply-jason-brother.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/delete-all-branches-but-main.cmd.in"
    "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/qiven.cmd.in"
)

foreach(path IN LISTS cmd_templates)
    file(READ "${path}" content)
    string(REGEX MATCH "if[^\r\n]*&[ \t]*exit /b" unsafe_if_chain "${content}")
    if(NOT unsafe_if_chain STREQUAL "")
        message(FATAL_ERROR
            "Unsafe generated CMD conditional in ${path}: ${unsafe_if_chain}\n"
            "Group the conditional body with parentheses or use goto-safe control flow; do not place '& exit /b' on an ungrouped IF line.")
    endif()
endforeach()

set(qiven_entrypoint "${DEVKIT_ROOT}/templates/cpp-library/managed/tools/qiven.cmd.in")
file(READ "${qiven_entrypoint}" qiven_content)
string(REGEX MATCH "exit /b[ \t]+%errorlevel%" unsafe_qiven_errorlevel "${qiven_content}")
if(NOT unsafe_qiven_errorlevel STREQUAL "")
    message(FATAL_ERROR
        "Unsafe qiven.cmd errorlevel propagation: ${unsafe_qiven_errorlevel}\n"
        "Do not expand %errorlevel% directly at exit sites that may move into parenthesized CMD blocks; capture it into an explicit variable using goto-safe control flow.")
endif()

string(FIND "${qiven_content}" "where python >nul 2>nul" python_probe_index)
string(FIND "${qiven_content}" "where py >nul 2>nul" py_probe_index)
if(python_probe_index EQUAL -1 OR py_probe_index EQUAL -1)
    message(FATAL_ERROR "qiven.cmd must probe both python and py compatibility fallback")
endif()
if(python_probe_index GREATER py_probe_index)
    message(FATAL_ERROR "qiven.cmd must prefer python before the legacy py launcher fallback")
endif()

string(REGEX MATCHALL "sys\\.version_info >= \\(3, 9\\)" qiven_version_checks "${qiven_content}")
list(LENGTH qiven_version_checks qiven_version_check_count)
if(qiven_version_check_count LESS 3)
    message(FATAL_ERROR
        "qiven.cmd must validate Python 3.9+ for QIVEN_PYTHON, python, and py -3 candidates")
endif()

message(STATUS "Generated CMD control-flow regression checks passed")
