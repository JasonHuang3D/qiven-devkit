# cpp-app shares the cpp-library managed surface (conventions, format
# configs, launcher + operator policy); only the bootstrap scaffold differs
# (library + application executable). Versions roll in lockstep. (WR-6
# template 0.1.10: no operator snapshot, no engineering docs in the managed
# set — engineering law lives in the Devkit, ADR-0046.)
set(QIVEN_MANAGED_SOURCE_DIR "${CMAKE_CURRENT_LIST_DIR}/../cpp-library")
include("${QIVEN_MANAGED_SOURCE_DIR}/managed-files.cmake")
set(QIVEN_FILE_CLASS bootstrap-only)
set(QIVEN_BOOTSTRAP_FILES
    .gitignore
    README.md
    CMakeLists.txt
    app/main.cpp
    .github/workflows/ci.yml
)
