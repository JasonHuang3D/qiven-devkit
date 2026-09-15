cmake_minimum_required(VERSION 3.28)

if(NOT DEFINED DEVKIT_ROOT)
    get_filename_component(DEVKIT_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
endif()

function(build_fail message_text)
    message(FATAL_ERROR "BUILD-SYSTEM TEST FAILURE: ${message_text}")
endfunction()

function(build_run_success)
    execute_process(COMMAND ${ARGV} RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE error)
    if(NOT result EQUAL 0)
        build_fail("command failed (${result}): ${ARGV}\n${output}\n${error}")
    endif()
endfunction()

function(build_run_failure expected)
    execute_process(COMMAND ${ARGN} RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE error)
    if(result EQUAL 0)
        build_fail("command unexpectedly succeeded: ${ARGN}")
    endif()
    string(FIND "${output}\n${error}" "${expected}" position)
    if(position EQUAL -1)
        build_fail("failure omitted expected text '${expected}':\n${output}\n${error}")
    endif()
endfunction()

string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef nonce)
cmake_path(CONVERT "$ENV{TEMP}" TO_CMAKE_PATH_LIST temp_root NORMALIZE)
set(root "${temp_root}/qiven-build-system-${nonce}")
file(MAKE_DIRECTORY "${root}")
function(build_generate kind path repo target alias namespace test_option)
    build_run_success(
        "${CMAKE_COMMAND}"
        -DDEVKIT_ROOT=${DEVKIT_ROOT}
        -DTEMPLATE_KIND=${kind}
        -DDESTINATION=${path}
        -DREPOSITORY_NAME=${repo}
        -DCMAKE_PROJECT_NAME=${repo}
        -DCMAKE_TARGET_NAME=${target}
        -DCMAKE_ALIAS=${alias}
        -DCPP_NAMESPACE=${namespace}
        -DTEST_OPTION_NAME=${test_option}
        -DVS_SOLUTION_NAME=${repo}
        -P "${DEVKIT_ROOT}/cmake/QivenRepoNew.cmake"
    )
endfunction()

set(lib "${root}/lib")
set(app "${root}/app")
build_generate(cpp-library "${lib}" lib-a lib-a qiven::lib_a qiven::lib_a LIB_A_TESTS)
build_generate(cpp-app "${app}" app-b app-b qiven::app_b qiven::app_b APP_B_TESTS)

set(super "${root}/super")
file(MAKE_DIRECTORY "${super}")
file(WRITE "${super}/CMakeLists.txt" "cmake_minimum_required(VERSION 3.28)\nproject(super LANGUAGES CXX)\nadd_subdirectory(\"${lib}\" lib)\nadd_subdirectory(\"${app}\" app)\n")
build_run_success("${CMAKE_COMMAND}" -S "${super}" -B "${root}/super-build")
file(READ "${app}/cmake/qiven/QivenBuild.cmake" app_build_module)
string(REPLACE
    "set(_qiven_requested_build_api \"1\")"
    "set(_qiven_requested_build_api \"2\")"
    app_build_module
    "${app_build_module}"
)
file(WRITE "${app}/cmake/qiven/QivenBuild.cmake" "${app_build_module}")
build_run_failure(
    "Incompatible Qiven build-system APIs"
    "${CMAKE_COMMAND}" -S "${super}" -B "${root}/super-mismatch-build"
)

set(dep_parent "${root}/dep-parent")
set(dep_child "${root}/dep-child")
file(MAKE_DIRECTORY "${dep_parent}" "${dep_child}")
file(COPY "${lib}/cmake" DESTINATION "${dep_parent}")
file(WRITE "${dep_child}/marker.txt" "lower\n")
file(WRITE "${dep_child}/CMakeLists.txt" [=[
cmake_minimum_required(VERSION 3.28)
project(lower LANGUAGES CXX)
option(LOWER_BUILD_TESTS "lower tests" ON)
if(LOWER_BUILD_TESTS)
    message(FATAL_ERROR "lower tests were not suppressed")
endif()
add_library(lower INTERFACE)
add_library(qiven::lower ALIAS lower)
]=])
file(WRITE "${dep_parent}/CMakeLists.txt"
    "cmake_minimum_required(VERSION 3.28)\n"
    "project(dep-parent LANGUAGES CXX)\n"
    "list(PREPEND CMAKE_MODULE_PATH \"${dep_parent}/cmake/qiven\")\n"
    "include(QivenBuild)\n"
    "set(LOWER_BUILD_TESTS ON)\n"
    "set(LOWER_ROOT \"${dep_child}\")\n"
    "qiven_resolve_source_dependency(NAME lower TARGET qiven::lower ROOT_VARIABLE LOWER_ROOT DEFAULT_SIBLING dep-child BUILD_SUBDIR lower TEST_OPTION LOWER_BUILD_TESTS REQUIRED_PATHS marker.txt)\n"
    "if(NOT LOWER_BUILD_TESTS)\n  message(FATAL_ERROR \"dependency test option leaked into parent scope\")\nendif()\n"
)
build_run_success("${CMAKE_COMMAND}" -S "${dep_parent}" -B "${root}/dep-build")

set(strict "${root}/strict")
file(MAKE_DIRECTORY "${strict}")
file(COPY "${lib}/cmake" DESTINATION "${strict}")
file(WRITE "${strict}/dummy.cpp" "int qiven_dummy() { return 0; }\n")
file(WRITE "${strict}/CMakeLists.txt"
    "cmake_minimum_required(VERSION 3.28)\n"
    "project(strict LANGUAGES CXX)\n"
    "list(PREPEND CMAKE_MODULE_PATH \"${strict}/cmake/qiven\")\n"
    "include(QivenBuild)\n"
    "add_library(strict STATIC dummy.cpp)\n"
    "qiven_target_defaults(strict TYPO should-fail)\n"
)
build_run_failure("unknown arguments" "${CMAKE_COMMAND}" -S "${strict}" -B "${root}/strict-build")
set(test_project "${root}/test-project")
file(MAKE_DIRECTORY "${test_project}")
file(COPY "${lib}/cmake" DESTINATION "${test_project}")
file(WRITE "${test_project}/main.cpp" "int main() { return 0; }\n")
file(WRITE "${test_project}/CMakeLists.txt"
    "cmake_minimum_required(VERSION 3.28)\n"
    "project(test-project LANGUAGES CXX)\n"
    "list(PREPEND CMAKE_MODULE_PATH \"${test_project}/cmake/qiven\")\n"
    "include(QivenBuild)\n"
    "qiven_project_defaults()\n"
    "add_executable(smoke main.cpp)\n"
    "qiven_test_target_defaults(smoke)\n"
    "enable_testing()\n"
    "qiven_register_test(NAME smoke TARGET smoke)\n"
)
set(test_build "${root}/test-build")
build_run_success("${CMAKE_COMMAND}" -S "${test_project}" -B "${test_build}")
build_run_success("${CMAKE_COMMAND}" --build "${test_build}" --config Debug)
build_run_success("${CMAKE_CTEST_COMMAND}" --test-dir "${test_build}" -C Debug --output-on-failure)

file(REMOVE_RECURSE "${root}")
if(EXISTS "${root}")
    build_fail("fixture cleanup failed: ${root}")
endif()
message(STATUS "Qiven native build-system contract tests passed")
