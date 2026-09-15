set(QIVEN_TEMPLATE_VERSION "0.2.0")
include("${CMAKE_CURRENT_LIST_DIR}/../native-common/managed-files.cmake")

set(QIVEN_MANAGED_SOURCE_ROOTS
    "${CMAKE_CURRENT_LIST_DIR}/../native-common/managed"
)
set(QIVEN_MANAGED_FILES ${QIVEN_NATIVE_MANAGED_FILES})

set(QIVEN_BOOTSTRAP_FILES
    .gitignore
    README.md
    CMakeLists.txt
    .github/workflows/ci.yml
    app/main.cpp
)
