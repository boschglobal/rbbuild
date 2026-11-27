<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# Tests

This document describes the test suite for *rbbuild*, covering the test prerequisites, local execution, and the overall test architecture.

---

## Overview

The test suite is split into two directories:

- **`test/unit/`** — fast, isolated tests that exercise individual classes and functions directly, without involving DI containers, config files, or external tools.
- **`test/integration/`** — end-to-end CLI tests that exercise the full tool stack in a hermetic, offline environment.

### Integration test files

| Test file | Tools under test |
|---|---|
| `test_concat_files.py` | `concat_files` |
| `test_pkq.py` | `pkq` |
| `test_promote.py` | `promote` |
| `test_pypa.py` | `rbbuild` (PyPA build system) |
| `test_python_native.py` | Examples that build a platform-specific Python wheel with C code (`python-ctypes-c`, `python-cext-c`) |
| `test_local_repository.py` | Local repository of the `standalone` profile: created on the first publish |
| `test_rbbconf.py` | `rbbconf` |
| `test_rbbuild.py` | `rbbuild` |
| `test_rbfoss.py` | `rbfoss` |
| `test_sbom.py` | `rbbuild` (SBOM/CycloneDX output) |

### Unit test files

| Test file | What it covers |
|---|---|
| `test_promote.py` | `parse_command_line`, `PromoteMain.do_promote`, `PromoteMain.main`, `RepositoryManager.promote` |
| `test_configuration.py` | `RBBuildConfiguration.load_project_configuration` — all `[project]`, `[rbbuild]`, `[cmake]`, `[oss]`, `[packaging]`, `[pandoc]`, `[sphinx]`, `[dependencies]` items via pyproject.toml; same sections via rbbuild.toml alone; merge precedence and key preservation when both files are present; environment variable overrides |
| `test_core.py` | `Toolchain`, `Channel`, `Paths`, `TempFolder` |
| `test_deps_parser.py` | `DepsParser` — all input formats, PURL, range syntax |
| `test_documentation_runner.py` | `DocumentationRunner` — dispatches configured documentation backends and skips unconfigured ones |
| `test_diff.py` | `PackageDiff`, `CompareResult` — compare states, dependency traversal, output text |
| `test_fossid.py` | `FossID` service |
| `test_jenkinsfile.py` | `Jenkinsfile` parser |
| `test_jira.py` | Jira issue tracker service, `IssueTrackerManager`, `Issue.status_colored` |
| `test_manifest.py` | `Manifest` load/write, `PackageParser` legacy parsing |
| `test_package.py` | `Package` construction, manifest parsing, components, merge |
| `test_package_types.py` | `License`, `ComponentSpecifier`, and other package type helpers |
| `test_purl_parser.py` | `PURLParser` — rbbuild and generic PURL strings |
| `test_pypa.py` | `PyPA` — name normalisation, package creation, licence resolution, `_requirements_satisfied`, `_build_only_names`, `build_only` propagation, and `execute_pip()` venv bootstrap path |
| `test_remote_service.py` | `RemoteService` — all `AuthMethod` variants, `AuthMethod.from_config` |
| `test_manager_auth_method.py` | `auth-method` of the remote service is passed by the CI, issue tracker, OSS, and SCM managers |
| `test_config_roots.py` | `load_config_roots` (entry-point group `rbbuild.config`), `load_profile` with configuration roots: sources, precedence, shared remote services, `ruff.toml` of profiles |
| `test_repository.py` | `Repository.list_versions`, `find_components` component name forwarding |
| `test_repository_plugins.py` | `load_repository_plugins` — entry-point group lookup, skipping unloadable and non-`Repository` plugins |
| `test_resolver.py` | `Resolver` — `run()`, `collect()`, `walk_deps_with_parent()`, `walk_deps_with_count()` |
| `test_staging_index_db.py` | `StagingIndexDB` — `store()` writes only when package snapshot data exists |
| `test_sbom.py` | `SBOM` generation and CycloneDX schema, CSI package handling |
| `test_sbom_overrides.py` | SBOM license and metadata overrides via `deps.json` |
| `test_metadata.py` | `Metadata` — name (config, git), version components, branch (config, git) |
| `test_version.py` | `__version__`, `RBBuildVersion`, `version_sort_function` |
| `test_artifactory.py` | `Artifactory.upload_component()` version-conflict detection |
| `test_s3.py`, `test_sigv4.py` | `S3` repository against a mocked endpoint; AWS Signature Version 4 (documented AWS examples) |
| `test_google_drive.py`, `test_oauth2.py` | `GoogleDrive` repository against a fake Drive API; OAuth 2.0 refresh-token authentication |
| `test_bash_completion.py` | Option lists of the bash completion script match the argparse parsers |
| `test_build.py` | PEP 517 build backend `rbbuild.buildsystem.build` — wheels, source distributions, entry points |
| `test_ci_manager.py` | `job_url()` of the CI services (Jenkins, GitHub Actions) |
| `test_cmake_python.py` | CMake arguments that depend on the Python toolchain |
| `test_data_path.py` | `rbbuild.data_path()` for installed and editable installations |
| `test_deps_editor_control.py` | Controller of the dependency editor (GUI) |
| `test_deps_patcher.py`, `test_deps_serializer.py` | Rewriting and serializing the `[dependencies]` table of `rbbuild.toml` and `pyproject.toml` |
| `test_local_file_service.py` | Local file repository service |
| `test_main_publish.py` | `RBBuildMain.publish()` version-conflict retry loop |
| `test_main_tools.py` | `RBBuildMain` — selection of build, test and SCA tools (`build-tools`, `test-tools`, `sca-tools`) |
| `test_package_toolchain.py` | Packages without toolchain (`none-any`) and their names |
| `test_packaging.py` | `[packaging]` entries — file resolution, `strip` and `dest` |
| `test_pkq_history.py` | `PkqHistory` — recent queries of the pkq GUI |
| `test_project_control.py`, `test_rbbuild_settings_control.py` | Controllers of the project and settings editors (GUI) |
| `test_ctest.py` | `CTest` build tool — availability, `ctest` call |
| `test_pytest_buildtool.py` | `PyTest` build tool — environment handling |
| `test_rbbuild_gui.py` | `build_application()` of `rbbuild-gui` |
| `test_rbbuild_tools.py` | Tool entries of the SBOM (`rbbuild` and the profile supplier) |
| `test_repository_manager.py` | `RepositoryManager` — search, toolchain fallback, service types |
| `test_rest_helper.py` | HTTP download and upload helper |
| `test_ruff.py` | `Ruff` build tool — selection and generation of the ruff configuration, `--sca` call |
| `test_sphinx.py` | Sphinx documentation setup |
| `test_toolchain_setting.py` | `default_toolchain_setting` — spellings of the default toolchain in `rbbconf -s` |
| `test_staging_folder.py` | Installing and removing packages in the staging folder |
| `test_user_config_file.py` | `UserConfigFile` — keys and sections of the user configuration |
| `test_utility.py` | `version_sort_function` and other helpers |
| `test_pkq_controller.py` | `PkqController` (pkq GUI) — toolchain listing/switching, query() for both plain and diff (`pkgA..verB`) syntax, selection, conflict diagnostics |

Integration tests share the fixtures defined in `test/integration/conftest.py`; unit tests share those in `test/unit/conftest.py`.

---

## Prerequisites

### Python version

Python **3.14 or higher** is required (the same constraint as the main package).

### Python packages

Install the development dependency-group from the project root:

```shell
uv pip install -e .[ui] --group dev
```

This pulls in the main dependencies and test-related dependencies.

All other runtime dependencies (`dependency-injector`, `gitpython`, etc.) are installed automatically as part of `pip install -e .`.

### No external service access required

The integration tests are **fully offline**. They use a local filesystem-based fake Artifactory repository located at `test/data/fake_artifactory/`. No credentials, VPN, or real Artifactory/Bitbucket connectivity is needed.

The `fake_artifactory` service of the builtin `test` profile derives its URL from `RBB_CONFIG_PATH` (`share/rbbuild/config/../../../test/data`), so the tests are portable across machines and the profile can also be used manually from a source checkout (`rbbuild -P test`).

---

## Test data layout

```
test/
├── data/
│   ├── fake_artifactory/           # Local stand-in for a binary repository
│   │   ├── generate_example_data.py  # Generates the repositories below
│   │   ├── sample-development-local/      # "test" profile: conflict_demo, sample_tools
│   │   └── example-development-local/     # "test" profile: libfoo, libbar, libbaz, testtool, testlib
│   └── user_home/                  # Simulated ~/.config/rbbuild
│       └── .config/rbbuild/
│           └── rbbuild.toml        # User config (selects the "test" profile, service credentials)
├── integration/
│   ├── conftest.py
│   ├── test_concat_files.py
│   ├── test_local_repository.py
│   ├── test_pkq.py
│   ├── test_promote.py
│   ├── test_pypa.py
│   ├── test_python_native.py
│   ├── test_rbbconf.py
│   ├── test_rbbuild.py
│   ├── test_rbfoss.py
│   └── test_sbom.py
└── unit/
    ├── test_pypa.py
    └── ...
```

> **Config file format:** all profile and service configuration files use TOML (`.toml`). The older INI format (`.ini`) is no longer read by the code.

### Profiles used by the tests

The tests use the real configuration in `share/rbbuild/config` (`RBB_CONFIG_PATH`). Two builtin profiles are relevant:

- `test` (`share/rbbuild/config/profiles/test`): channels, fake services (`fake_artifactory`, `fossid_service`, `jira_service`) and OSS/issue tracker settings for the fake repositories. The simulated user config in `test/data/user_home` makes it the default profile and provides the service credentials.
- `standalone` (`share/rbbuild/config/profiles/standalone`): the default profile without user config. Tests that verify the shipped defaults, such as the local repository, use the `rbbconf_empty`, `rbbuild_empty`, `pkq_empty` and `rbfoss_empty` fixtures, which run with an empty user home.

### Fake repositories

The repositories in `test/data/fake_artifactory/` contain only generic, synthetic packages. They are generated by `generate_example_data.py` (run it from the project root); the output is deterministic, so the committed files only change when the generator changes.

| Package | Repository | Purpose |
|---|---|---|
| `libfoo` | `example-development-local` | Versions `1.0.0.1`, `1.1.0.2`, `2.0.0.3` for `linux-native` and `win32-mingw`; the files of the `prod` and `dev` components differ between 1.x and 2.x (upgrade/downgrade tests) |
| `libbar` | `example-development-local` | Depends on `libfoo` and (build-only) on `testtool`; the latest version `3.0.0.3` exists only for `linux-ubuntu-armhf` (toolchain fallback tests) |
| `testtool`, `testlib` | `example-development-local` | Build-only dependency chain |
| `libbaz` | `example-development-local` | Six versions without components (sorting and query limit tests) |
| `sample_tools` | `sample-development-local` | Components `alpha`, `beta`, `gamma` and a build-only `sbom`; `1.0.0.2` exists only for `linux-native` |
| `conflict_demo` | `sample-development-local` | Version with a 5th "conflict" digit |

Tests for legacy manifests and legacy version formats are not part of this repository.

---

## Running the tests

All commands below must be run from the **repository root** (the directory that contains `pyproject.toml`).

### Run the full test suite (unit + integration)

```shell
pytest
```

### Run only the integration tests

```shell
pytest test/integration/
```

### Run only the unit tests

```shell
pytest test/unit/
```

### Run a single integration test file

```shell
pytest test/integration/test_rbbconf.py
```

### Run a single test by name

```shell
pytest test/integration/test_rbbuild.py::test_rbbuild_fi
```

### Run with increased verbosity

```shell
pytest -v test/integration/
```

### Stop after the first failure

The default `pytest.ini_options` already adds `-x` (stop on first failure) and `-v` (verbose). To override and continue on failure:

```shell
pytest -p no:randomly --no-header -x- test/integration/
```

Or simply pass `-x-` to disable fail-fast:

```shell
pytest test/integration/ -x-
```

### Show captured console output

Test output is captured to per-tool console files (UTF-8 encoded) inside the tmp directory. On test failure, pytest prints the location. To see the raw output of a specific run, add `-s`:

```shell
pytest test/integration/test_rbbconf.py -s
```

---

## pytest configuration

The project's `pyproject.toml` sets the following defaults:

```toml
[tool.pytest.ini_options]
minversion = '8.0'
addopts    = ['-xv', '--import-mode=importlib']
testpaths  = ['test']
pythonpath = ['.']
```

| Option | Effect |
|---|---|
| `-x` | Stop after the first failing test |
| `-v` | Verbose output (test names printed) |
| `--import-mode=importlib` | Ensures correct module isolation across unit and integration |
| `pythonpath = ['.']` | Adds the repo root to `sys.path` so `rbbuild.*` imports resolve without installation |

---

## Test architecture

### `conftest.py` — fixture hierarchy

#### Integration tests (`test/integration/conftest.py`)

A shared `source_path` fixture creates a fresh, empty `tmp_path/project/` directory that is used as the simulated project working directory by all tool fixtures (except `concat_files`, which manages its own subdirectory):

```
tmp_path ──► source_path ──┬──► rbbuild
                           ├──► rbbconf
                           ├──► rbbconf_empty
                           ├──► rbbuild_empty
                           ├──► pkq
                           ├──► pkq_empty
                           ├──► promote
                           ├──► rbfoss
                           └──► rbfoss_empty

user_home_empty ──► rbbconf_empty, rbbuild_empty, pkq_empty, rbfoss_empty

user_home       ──┬──► rbbuild
                  ├──► rbbconf
                  ├──► pkq
                  ├──► promote
                  ├──► rbfoss
                  └──► concat_files
```

Each fixture yields a tool wrapper (`TestRBBuild`, `TestRBBConf`, `TestPKQ`, etc.) that provides:

- `run(args: list[str])` — sets up the environment, wires the DI container, calls `main()`, and tears down.
- `read_console() -> str` — returns the captured terminal output from the last `run()` call, decoded as UTF-8.


#### Unit tests (`test/unit/conftest.py`)

The unit conftest provides lightweight shared fixtures that do not require CLI tool wiring:

| Fixture | What it provides |
|---|---|
| `app` | A fully wired `Application` DI container using the `test` profile |
| `app_test` | Same as `app` (kept for tests that select the profile explicitly) |
| `fake_project` | A per-test copy of `test/data/fake_project/` at `tmp_path/` |
| `fossid` | A `FossID` service instance wired from `app_test` (reads `profile.oss.*` config) |
| `jira` | A `Jira` service instance wired from `app_test` |

Both `app` and `app_test` call `application.unwire()` on teardown.


### DI wiring in tests

Each tool's `run()` method replicates the exact configuration-loading sequence performed by the production `run()` function in the corresponding module:

| Tool | Config-loading sequence |
|---|---|
| `rbbuild` | `load_cli_source_path` → `load_pyproject_toml` → `load_jenkinsfile` → `load_cli_profile` → `load_profile` → `load_cli` → `load_cli_rbbuild` |
| `pkq` | `load_cli_profile` → `load_profile` → `load_cli` |
| `promote` | `load_cli_profile` → `load_profile` → `load_cli` |
| `rbbconf` | `load_cli` → `load_profile` |
| `rbfoss` | `load_pyproject_toml` → `load_jenkinsfile` → `load_cli_profile` → `load_profile` → `load_cli` |

After each `run()`, `application.unwire()` is called in a `finally` block to ensure no DI state leaks between tests.


### Environment isolation

Each test receives a fresh `tmp_path` (pytest's built-in) containing:

- A copy of `test/data/user_home` as the simulated `$HOME/.config/rbbuild` directory.
- A fresh empty working directory as the simulated project source root.

The following environment variables are patched for the duration of each `run()` call:

| Variable | Value set by fixture |
|---|---|
| `HOME` | Path to the per-test `user_home` tmp directory |
| `RBB_CONFIG_PATH` | `share/rbbuild/config` |
| `PYTHONUSERBASE` | Preserved from the real environment (so installed tools like CMake remain on `PATH`) |
| `sys.argv` | Set to `[exe, *args]` |

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'rbbuild'`
The package must be installed in the active Python environment. Run `pip install -e . --group dev` (or `uv pip install -e . --group dev`) from the repo root.

### Tests fail with TOML parse errors
Ensure the config files under `test/data/` are `.toml` files (not `.ini`). The TOML format is required; INI files are silently ignored.

### `LookupError: Could not find profile standalone`
`RBB_CONFIG_PATH` is not pointing at the correct location. When running with `pytest` from the repo root, this is set automatically by the fixture. If running tests manually or from an IDE, ensure the working directory is the repository root.

### Tests that depend on `fake_artifactory` fail with file-not-found errors
The `fake_artifactory` service URL is derived from `RBB_CONFIG_PATH` (`share/rbbuild/config/../../../test/data`). The working directory at fixture-setup time must be the repository root.
