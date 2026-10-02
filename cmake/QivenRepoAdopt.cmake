include("${CMAKE_CURRENT_LIST_DIR}/QivenRepoCommon.cmake")

foreach(variable IN ITEMS DEVKIT_ROOT MODE REPOSITORY REPOSITORY_NAME CMAKE_PROJECT_NAME CMAKE_TARGET_NAME CMAKE_ALIAS CPP_NAMESPACE TEST_OPTION_NAME VS_SOLUTION_NAME)
    qiven_validate_value(${variable})
endforeach()
if(NOT MODE STREQUAL "check" AND NOT MODE STREQUAL "apply")
    message(FATAL_ERROR "MODE must be exactly check or apply\n"
        "  rule: qivenrepo/adopt/mode-law (MODE is case-sensitive: check | apply)\n"
        "  evidence: got MODE='${MODE}'\n"
        "  NEXT: FIX - re-run with MODE check (read-only plan) or apply (materialize), "
        "spelled exactly")
endif()

cmake_path(ABSOLUTE_PATH REPOSITORY NORMALIZE OUTPUT_VARIABLE repository)
if(NOT IS_DIRECTORY "${repository}")
    message(FATAL_ERROR "Repository path does not exist or is not a directory: ${repository}\n"
        "  rule: qivenrepo/adopt/target-missing (adoption needs the repository root)\n"
        "  evidence: resolved path ${repository}\n"
        "  NEXT: FIX - pass the root path of the repository to adopt, then re-run")
endif()

find_program(QIVEN_GIT_EXECUTABLE NAMES git REQUIRED)
execute_process(COMMAND "${QIVEN_GIT_EXECUTABLE}" -C "${repository}" rev-parse --show-toplevel
    RESULT_VARIABLE root_result OUTPUT_VARIABLE git_root ERROR_VARIABLE root_error OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT root_result EQUAL 0)
    message(FATAL_ERROR "Target is not a Git working tree: ${repository}\n${root_error}\n"
        "  rule: qivenrepo/adopt/not-a-work-tree (adoption records ownership in git "
        "state, so the target must be one)\n"
        "  NEXT: FIX - initialize the repository (git init) or point REPOSITORY at "
        "the real work tree, then re-run")
endif()
file(REAL_PATH "${repository}" repository_real)
file(REAL_PATH "${git_root}" git_root_real)
if(WIN32)
    string(TOLOWER "${repository_real}" repository_compare)
    string(TOLOWER "${git_root_real}" git_root_compare)
else()
    set(repository_compare "${repository_real}")
    set(git_root_compare "${git_root_real}")
endif()
if(NOT repository_compare STREQUAL git_root_compare)
    message(FATAL_ERROR "Target must be the root of its Git working tree: ${repository}\n"
        "  rule: qivenrepo/adopt/not-work-tree-root (adoption plans against the tree "
        "root so nothing outside ownership is touched)\n"
        "  evidence: passed ${repository}; git root resolves to ${git_root}\n"
        "  NEXT: FIX - re-run with REPOSITORY=${git_root}")
endif()

execute_process(COMMAND "${QIVEN_GIT_EXECUTABLE}" -C "${repository}" rev-parse --verify HEAD
    RESULT_VARIABLE head_result OUTPUT_QUIET ERROR_VARIABLE head_error)
if(NOT head_result EQUAL 0)
    message(FATAL_ERROR "Target Git repository has no HEAD commit: ${repository}\n${head_error}\n"
        "  rule: qivenrepo/adopt/no-head (a baseline commit is required so adoption "
        "conflicts are diffable and reversible)\n"
        "  NEXT: FIX - commit the current state first (git add --all; git commit), "
        "then re-run")
endif()
if(EXISTS "${repository}/.qiven" OR IS_SYMLINK "${repository}/.qiven")
    message(FATAL_ERROR "Target already contains .qiven ownership state; use sync-repo for an already-managed repository\n"
        "  rule: qivenrepo/adopt/already-managed (adoption is for unmanaged "
        "repositories; a managed one is updated by sync, never re-adopted)\n"
        "  evidence: ${repository}/.qiven exists\n"
        "  NEXT: FIX - run the sync path instead: python tools/sync_repo.py "
        "\"${repository}\"")
endif()
execute_process(COMMAND "${QIVEN_GIT_EXECUTABLE}" --no-optional-locks -C "${repository}" status --porcelain=v1 --untracked-files=all
    RESULT_VARIABLE status_result OUTPUT_VARIABLE porcelain ERROR_VARIABLE status_error)
if(NOT status_result EQUAL 0)
    message(FATAL_ERROR "Could not inspect target Git status: ${status_error}\n"
        "  rule: qivenrepo/adopt/status-unreadable (the clean-tree precondition "
        "cannot be established, so adoption does not proceed)\n"
        "  NEXT: DIAGNOSE - run git -C \"${repository}\" status --porcelain=v1 "
        "--untracked-files=all yourself; fix the git condition it reports, then re-run")
endif()
if(NOT porcelain STREQUAL "")
    message(FATAL_ERROR "Target Git repository is not clean; adoption made no changes\n"
        "  rule: qivenrepo/adopt/dirty-tree (adoption requires a clean tree so no "
        "consumer work is overwritten or hidden by the plan)\n"
        "  evidence: git status --porcelain=v1 --untracked-files=all reports:\n"
        "${porcelain}\n"
        "  NEXT: FIX - commit or stash every path listed above, then re-run")
endif()
set(template "${DEVKIT_ROOT}/templates/cpp-library")
include("${template}/managed-files.cmake")
string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef nonce)
set(stage "${repository}.qiven-adopt-${nonce}")
cmake_path(IS_PREFIX repository "${stage}" stage_inside_repository NORMALIZE)
if(stage_inside_repository)
    message(FATAL_ERROR "Could not place adoption staging outside the target repository: ${repository}\n"
        "  rule: qivenrepo/adopt/stage-inside-target (staging must never pollute the "
        "clean-tree plan it is building)\n"
        "  NEXT: DIAGNOSE - this is a path-layout collision, not an input class; "
        "inspect ${stage}, then re-run")
endif()
if(EXISTS "${stage}" OR IS_SYMLINK "${stage}")
    message(FATAL_ERROR "Temporary path already exists: ${stage}\n"
        "  rule: qivenrepo/adopt/stage-collision (a random-nonce staging dir already "
        "exists - unexpected, not a normal input class)\n"
        "  NEXT: DIAGNOSE - inspect and remove the stale staging dir, then re-run")
endif()
file(MAKE_DIRECTORY "${stage}")

foreach(relative IN LISTS QIVEN_MANAGED_FILES)
    qiven_validate_managed_path("${relative}")
    qiven_render("${template}/managed/${relative}.in" "${stage}/${relative}")
endforeach()
file(MAKE_DIRECTORY "${stage}/.qiven")
qiven_render("${template}/repo.json.in" "${stage}/.qiven/repo.json")
qiven_write_state("${stage}" "${stage}")

set(exact_paths "")
set(missing_paths "")
set(conflict_paths "")
foreach(relative IN LISTS QIVEN_MANAGED_FILES)
    set(parent_collision FALSE)
    get_filename_component(parent_relative "${relative}" DIRECTORY)
    while(NOT parent_relative STREQUAL "")
        if(IS_SYMLINK "${repository}/${parent_relative}" OR
                (EXISTS "${repository}/${parent_relative}" AND NOT IS_DIRECTORY "${repository}/${parent_relative}"))
            set(parent_collision TRUE)
            break()
        endif()
        get_filename_component(parent_relative "${parent_relative}" DIRECTORY)
    endwhile()
    if(parent_collision OR IS_DIRECTORY "${repository}/${relative}" OR IS_SYMLINK "${repository}/${relative}")
        list(APPEND conflict_paths "${relative}")
    elseif(NOT EXISTS "${repository}/${relative}")
        list(APPEND missing_paths "${relative}")
    else()
        qiven_hash("${repository}/${relative}" current_hash)
        qiven_hash("${stage}/${relative}" desired_hash)
        if(current_hash STREQUAL desired_hash)
            list(APPEND exact_paths "${relative}")
        else()
            list(APPEND conflict_paths "${relative}")
        endif()
    endif()
endforeach()

function(qiven_print_adoption_category label paths_variable)
    message(STATUS "${label}:")
    foreach(relative IN LISTS ${paths_variable})
        message(STATUS "  ${relative}")
    endforeach()
endfunction()

message(STATUS "Qiven adoption plan")
qiven_print_adoption_category("EXACT" exact_paths)
qiven_print_adoption_category("MISSING" missing_paths)
qiven_print_adoption_category("CONFLICT" conflict_paths)

if(conflict_paths)
    file(REMOVE_RECURSE "${stage}")
    list(JOIN conflict_paths ", " conflict_text)
    message(FATAL_ERROR "Adoption conflict; no repository files changed: ${conflict_text}\n"
        "  rule: qivenrepo/adopt/conflict (a managed path whose current bytes differ "
        "from the template render; adoption is all-or-nothing, so one conflict "
        "blocks everything and no repository file was touched)\n"
        "  evidence: conflicting path(s): ${conflict_text}; the desired bytes are "
        "the current devkit template render\n"
        "  NEXT: FIX - for each listed path: port your local change into the devkit "
        "template or restore the template bytes; commit, re-run MODE check, then "
        "MODE apply")
endif()

if(MODE STREQUAL "check")
    file(REMOVE_RECURSE "${stage}")
    message(STATUS "Adoption check passed; target repository was not changed")
    return()
endif()

foreach(relative IN LISTS missing_paths)
    get_filename_component(parent "${repository}/${relative}" DIRECTORY)
    file(MAKE_DIRECTORY "${parent}")
    execute_process(COMMAND "${CMAKE_COMMAND}" -E copy "${stage}/${relative}" "${repository}/${relative}"
        COMMAND_ERROR_IS_FATAL ANY)
endforeach()
file(MAKE_DIRECTORY "${repository}/.qiven")
execute_process(COMMAND "${CMAKE_COMMAND}" -E copy "${stage}/.qiven/repo.json" "${repository}/.qiven/repo.json"
    COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" -E copy "${stage}/.qiven/generated-state.cmake" "${repository}/.qiven/generated-state.cmake"
    COMMAND_ERROR_IS_FATAL ANY)
file(REMOVE_RECURSE "${stage}")
message(STATUS "Adopted ${REPOSITORY_NAME} at ${repository}")
