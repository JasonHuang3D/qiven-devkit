cmake_minimum_required(VERSION 3.28)

if(NOT DEFINED DEVKIT_ROOT)
    get_filename_component(DEVKIT_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
endif()

function(fail message_text)
    message(FATAL_ERROR "TEST FAILURE: ${message_text}")
endfunction()

function(run_expect_success)
    execute_process(COMMAND ${ARGV} RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE error)
    if(NOT result EQUAL 0)
        fail("command failed (${result}): ${ARGV}\n${output}\n${error}")
    endif()
endfunction()

string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef nonce)
if(DEFINED ENV{TEMP} AND NOT "$ENV{TEMP}" STREQUAL "" AND IS_DIRECTORY "$ENV{TEMP}")
    set(fixture_parent "$ENV{TEMP}")
elseif(DEFINED ENV{TMPDIR} AND NOT "$ENV{TMPDIR}" STREQUAL "" AND IS_DIRECTORY "$ENV{TMPDIR}")
    set(fixture_parent "$ENV{TMPDIR}")
elseif(DEFINED ENV{TMP} AND NOT "$ENV{TMP}" STREQUAL "" AND IS_DIRECTORY "$ENV{TMP}")
    set(fixture_parent "$ENV{TMP}")
elseif(UNIX AND IS_DIRECTORY "/tmp")
    set(fixture_parent "/tmp")
else()
    fail("no usable temporary directory was found")
endif()

set(repo "${fixture_parent}/qiven-devkit-adopt-missing-sync-${nonce}")
include("${DEVKIT_ROOT}/templates/cpp-library/managed-files.cmake")

run_expect_success("${CMAKE_COMMAND}"
    -DDEVKIT_ROOT=${DEVKIT_ROOT} -DDESTINATION=${repo}
    -DREPOSITORY_NAME=adopt-missing-sync -DCMAKE_PROJECT_NAME=adopt-missing-sync
    -DCMAKE_TARGET_NAME=adopt-missing-sync -DCMAKE_ALIAS=qiven::example
    -DCPP_NAMESPACE=qiven::example -DTEST_OPTION_NAME=QIVEN_EXAMPLE_BUILD_TESTS
    -DVS_SOLUTION_NAME=adopt-missing-sync -P "${DEVKIT_ROOT}/cmake/QivenRepoNew.cmake")

file(REMOVE_RECURSE "${repo}/.qiven")
file(REMOVE "${repo}/.clang-format" "${repo}/tools/format.cmd")
run_expect_success(git -C "${repo}" init -b main)
run_expect_success(git -C "${repo}" add --all)
run_expect_success(git -C "${repo}" -c user.name=QivenFixture -c user.email=fixture@example.invalid commit -m baseline)

run_expect_success("${CMAKE_COMMAND}"
    -DDEVKIT_ROOT=${DEVKIT_ROOT} -DMODE=apply -DREPOSITORY=${repo}
    -DREPOSITORY_NAME=adopt-missing-sync -DCMAKE_PROJECT_NAME=adopt-missing-sync
    -DCMAKE_TARGET_NAME=adopt-missing-sync -DCMAKE_ALIAS=qiven::example
    -DCPP_NAMESPACE=qiven::example -DTEST_OPTION_NAME=QIVEN_EXAMPLE_BUILD_TESTS
    -DVS_SOLUTION_NAME=adopt-missing-sync -P "${DEVKIT_ROOT}/cmake/QivenRepoAdopt.cmake")

foreach(relative IN LISTS QIVEN_MANAGED_FILES)
    if(NOT EXISTS "${repo}/${relative}")
        fail("successful MISSING-path adoption did not materialize managed path: ${relative}")
    endif()
    string(SHA256 key "${relative}")
    file(SHA256 "${repo}/${relative}" before_${key})
endforeach()
foreach(relative IN ITEMS .qiven/repo.json .qiven/generated-state.cmake)
    if(NOT EXISTS "${repo}/${relative}")
        fail("successful MISSING-path adoption did not create ownership state: ${relative}")
    endif()
    string(SHA256 key "${relative}")
    file(SHA256 "${repo}/${relative}" before_${key})
endforeach()

run_expect_success("${CMAKE_COMMAND}" -DDEVKIT_ROOT=${DEVKIT_ROOT} -DREPOSITORY=${repo} -P "${DEVKIT_ROOT}/cmake/QivenRepoSync.cmake")

foreach(relative IN LISTS QIVEN_MANAGED_FILES)
    string(SHA256 key "${relative}")
    file(SHA256 "${repo}/${relative}" after_${key})
    if(NOT before_${key} STREQUAL after_${key})
        fail("immediate post-adoption sync changed managed content after MISSING-path adoption: ${relative}")
    endif()
endforeach()
foreach(relative IN ITEMS .qiven/repo.json .qiven/generated-state.cmake)
    string(SHA256 key "${relative}")
    file(SHA256 "${repo}/${relative}" after_${key})
    if(NOT before_${key} STREQUAL after_${key})
        fail("immediate post-adoption sync changed ownership state after MISSING-path adoption: ${relative}")
    endif()
endforeach()

file(REMOVE_RECURSE "${repo}")
if(EXISTS "${repo}")
    fail("fixture cleanup failed")
endif()
message(STATUS "MISSING-path adoption immediate sync no-op check passed")
