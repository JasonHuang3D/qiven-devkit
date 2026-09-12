set(QIVEN_TEMPLATE_VERSION "0.1.0")
set(QIVEN_FILE_CLASS managed)
set(QIVEN_MANAGED_FILES
    .clang-format
    .editorconfig
    .gitattributes
    CMakePresets.json
    AGENTS.md
    docs/engineering/README.md
    docs/engineering/implementation-standard.md
    docs/engineering/testing-standard.md
    docs/engineering/worker-protocol.md
    docs/engineering/feature-spec.md
    tools/resolve-toolchain.cmd
    tools/format.cmd
    tools/format-check.cmd
    tools/gen-vs2022-x64.cmd
    tools/apply-jason-brother.cmd
    tools/delete-all-branches-but-main.cmd
)
set(QIVEN_FILE_CLASS bootstrap-only)
set(QIVEN_BOOTSTRAP_FILES
    .gitignore
    README.md
    CMakeLists.txt
    .github/workflows/ci.yml
)
