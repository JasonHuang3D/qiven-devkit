set(QIVEN_TEMPLATE_VERSION "0.1.10")
set(QIVEN_FILE_CLASS managed)
set(QIVEN_MANAGED_FILES
    .clang-format
    .editorconfig
    .gitattributes
    CMakePresets.json
    AGENTS.md
    .qiven/operator.json
    tools/toolchain.py
    tools/check_toolchain.py
    tools/format_sources.py
    tools/apply_patch.py
    tools/qiven.cmd
    tools/qiven.py
    tools/delete_all_branches.py
)
# WR-6 (2026-09-28, v44): tools/qiven_operator.py is REMOVED from the
# managed set - generated repositories launch through the workspace
# bootstrap identity-check and import the LOCKED devkit operator; a new
# repository must not materialize a vendored operator copy (the retired
# ADR-0046 shim+pin class). The grandfathered repository-owned instances
# (qiven-foundation, qiven-runtime) predate this change and drifted from
# the canonical operator; a future sync of those repositories fails
# closed on the managed-file conflict until the wr6-report consolidation
# residual is adjudicated - by design, never silently.
set(QIVEN_FILE_CLASS bootstrap-only)
set(QIVEN_BOOTSTRAP_FILES
    .gitignore
    README.md
    CMakeLists.txt
    .github/workflows/ci.yml
)
