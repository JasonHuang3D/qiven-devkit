set(QIVEN_TEMPLATE_VERSION "0.1.5")
set(QIVEN_FILE_CLASS managed)
set(QIVEN_MANAGED_FILES
    .clang-format
    .editorconfig
    .gitattributes
    CMakePresets.json
    AGENTS.md
    .qiven/operator.json
    docs/engineering/README.md
    docs/engineering/implementation-standard.md
    docs/engineering/testing-standard.md
    docs/engineering/worker-protocol.md
    docs/engineering/feature-spec.md
    tools/toolchain.py
    tools/check_toolchain.py
    tools/format_sources.py
    tools/apply_patch.py
    tools/qiven.cmd
    tools/qiven.py
    tools/qiven_operator.py
    tools/delete_all_branches.py
)
set(QIVEN_FILE_CLASS bootstrap-only)
set(QIVEN_BOOTSTRAP_FILES
    .gitignore
    README.md
    CMakeLists.txt
    .github/workflows/ci.yml
)
