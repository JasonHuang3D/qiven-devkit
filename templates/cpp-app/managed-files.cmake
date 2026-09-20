# cpp-app shares the cpp-library managed surface (conventions, engineering
# docs, operator, format configs); only the bootstrap scaffold differs
# (library + application executable). Versions roll in lockstep.
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
