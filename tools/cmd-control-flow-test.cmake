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

message(STATUS "Generated CMD control-flow regression checks passed")
