include("${CMAKE_CURRENT_LIST_DIR}/QivenRepoCommon.cmake")
foreach(variable IN ITEMS DEVKIT_ROOT DESTINATION REPOSITORY_NAME CMAKE_PROJECT_NAME CMAKE_TARGET_NAME CMAKE_ALIAS CPP_NAMESPACE TEST_OPTION_NAME VS_SOLUTION_NAME)
    qiven_validate_value(${variable})
endforeach()
if(NOT DEFINED TEMPLATE)
    set(TEMPLATE "cpp-library")
endif()
if(NOT TEMPLATE MATCHES "^[a-z0-9-]+$")
    message(FATAL_ERROR "Invalid template family: ${TEMPLATE}\n"
        "  rule: qivenrepo/new/invalid-template-family (family ids are lowercase "
        "^[a-z0-9-]+$)\n"
        "  NEXT: FIX - pass a lowercase family id that exists under templates/ "
        "with a managed-files.cmake, then re-run")
endif()
if(NOT EXISTS "${DEVKIT_ROOT}/templates/${TEMPLATE}/managed-files.cmake")
    message(FATAL_ERROR "Unknown template family: ${TEMPLATE}\n"
        "  rule: qivenrepo/new/unknown-template-family (no "
        "templates/${TEMPLATE}/managed-files.cmake under ${DEVKIT_ROOT})\n"
        "  NEXT: FIX - use an existing family (cpp-library, cpp-app) or create "
        "templates/${TEMPLATE}/managed-files.cmake, then re-run")
endif()

cmake_path(ABSOLUTE_PATH DESTINATION NORMALIZE OUTPUT_VARIABLE destination)
if(EXISTS "${destination}")
    file(GLOB existing LIST_DIRECTORIES true "${destination}/*" "${destination}/.*")
    list(FILTER existing EXCLUDE REGEX "/\.\.?$")
    if(existing)
        message(FATAL_ERROR "Destination contains existing content: ${destination}\n"
            "  rule: qivenrepo/new/destination-not-empty (generation refuses to "
            "destroy existing content)\n"
            "  evidence: ${existing}\n"
            "  NEXT: FIX - point DESTINATION at an empty or nonexistent directory, "
            "or deliberately move the existing content away, then re-run")
    endif()
endif()

set(template "${DEVKIT_ROOT}/templates/${TEMPLATE}")
include("${template}/managed-files.cmake")
if(NOT DEFINED QIVEN_MANAGED_SOURCE_DIR)
    set(QIVEN_MANAGED_SOURCE_DIR "${template}")
endif()
set(TEMPLATE_KIND "${TEMPLATE}")
string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef nonce)
set(stage "${destination}.qiven-new-${nonce}")
if(EXISTS "${stage}")
    message(FATAL_ERROR "Temporary path already exists: ${stage}\n"
        "  rule: qivenrepo/new/stage-collision (a random-nonce staging dir already "
        "exists - unexpected, not a normal input class)\n"
        "  evidence: ${stage}\n"
        "  NEXT: DIAGNOSE - inspect and remove the stale staging dir, then re-run")
endif()
file(MAKE_DIRECTORY "${stage}")

foreach(relative IN LISTS QIVEN_MANAGED_FILES)
    qiven_validate_managed_path("${relative}")
    qiven_render("${QIVEN_MANAGED_SOURCE_DIR}/managed/${relative}.in" "${stage}/${relative}")
endforeach()
foreach(relative IN LISTS QIVEN_BOOTSTRAP_FILES)
    qiven_validate_managed_path("${relative}")
    qiven_render("${template}/bootstrap-only/${relative}.in" "${stage}/${relative}")
endforeach()

file(MAKE_DIRECTORY "${stage}/.qiven")
qiven_render("${template}/repo.json.in" "${stage}/.qiven/repo.json")
qiven_write_state("${stage}" "${stage}")

if(EXISTS "${destination}")
    file(REMOVE_RECURSE "${destination}")
endif()
file(RENAME "${stage}" "${destination}" RESULT rename_result)
if(rename_result)
    file(REMOVE_RECURSE "${stage}")
    message(FATAL_ERROR "Could not publish generated repository: ${rename_result}\n"
        "  rule: qivenrepo/new/publish-rename-failed (the staged tree rendered "
        "completely but the final rename did not land)\n"
        "  evidence: rename result ${rename_result}; staging was cleaned up\n"
        "  NEXT: DIAGNOSE - check locks/permissions on ${destination}, then re-run")
endif()
message(STATUS "Generated ${REPOSITORY_NAME} at ${destination}")
