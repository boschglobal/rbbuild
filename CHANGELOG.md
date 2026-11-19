<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# Version 6.1 (not yet released)

- Remote services can use the operating system trust store (corporate CA certificates) with
 `truststore = true` entry of `[profile.services.NAME]`.


# Version 6.0 (released 2026-10-28)

## Breaking changes

- Python 3.14 or newer is required.
- Updated manifest version (`json_version=5`).
- `rbbuild.toml` and `pyproject.toml` are used to configure rbbuild projects.
  Existing `deps.json`, `deps` and `version.properties` are still supported (legacy).
- Package versions no longer contain the branch name. Legacy wildcards such as
  `pkg::develop` are removed.
- The dependency attributes `foreign_toolchain` and `foreign_platform` are removed.
- Virtual channels `url:` and `bitbucket:` are replaced by plain URL or PackageURL strings.
- Dependency resolution is rewritten: top-level entries always win over nested requirements.
- Removed `rbbuild --param`, `--get` and `--print-all-conf`. Use the new `rbbconf` tool instead.
- `rbbuild -D` now generates documentation, and `pkq --changes/--git/--show-commits` are replaced
  by `--diff-mode`.
- `RBB_DEFAULT_CHANNEL` was renamed to `RBB_CHANNEL`.
- `RBB_PACKAGE_DEPENDENCIES` was removed.
- `RBB_TOOLCHAIN_ID` now holds the canonical ID (e.g., `linux-native`).
- The default toolchain (from the profile, e.g., `linux-native` or `win32-mingw`) is only used
  when the project is built with CMake. Other projects, such as pure Python, use `none-any`.
  `-t` always overrides this.
- Default toolchain set with `rbbconf -s toolchain=<tcid>` is stored as  `toolchain-<platform>` and overrides the default of the profile.
- RBPackage CMake module:
  - RPM packages are no longer built by default
  - `RBPackageSign` is removed
- Removed `clean_artifactory.py`
- `parse_manifest.py` is replaced by the new `rbfossid` tool.
- SonarQube scanner and the C-Family wrapper are no longer supported.
- Revamped user-configuration in `~/.config/rbbuild`.


## New features (highlights)

- rbbuild is distributed as fully-compliant Python wheel package. This means, standard tools
  like uv or pip can be used to install rbbuild.
- rbbuild itself provides a PEP 517 backend to package Python wheel packages:
  - support for multiple wheels per repository (single `rbbuild.toml`/`pyproject.toml`)
  - support for building wheels combined with C/C++ code (with rbbuild/CMake)
- `rbbuild.toml` for per-repository configuration, including default actions. Alternatively,
  projects can provide a `pyproject.toml` with rbbuild-specific entries under `[tool.rbbuild]`
  sections. This is handy for pure Python repositories.
- Automatic build tool detection (CMake, uv/pypa, npm) and custom build scripts.
- `rbbuild --publish` adds a fifth version digit on upload conflicts. New
  actions: `--upload`, `--delete`, `--licenses`.
- CycloneDX 1.6 SBOMs are created beside existing `manifest.json`.
- `rbbuild --sca` runs static code analysis with [ruff](https://docs.astral.sh/ruff/). Profiles
  can provide a common `ruff.toml`; project settings override it.
- `[tool.rbbuild]` has the new keys `test-tools` (`ctest`, `pytest`) and `sca-tools` (`ruff`).
  `pytest` is no longer a value of `build-tools`. Project values of `actions`, `build-tools`,
  `test-tools` and `sca-tools` override the defaults of `rbbuild.toml`.
- New tools:
  - `rbfoss`: OSS tool with FossID backend; replaces `parse_manifest.py`.
  - `rbbconf`: flexible rbbuild configuration tool
  - `rbbuild-gui`: rbbuild Command Center UI; replaces rbbuild GUI (`pkq -g`)
- Introduced profiles concept to rbbuild:
  - Organization- and project-specific configuration items and services are now outsourced
    into dedicated profile packages or user-specific files (in `~/.config/rbbuild/profiles`).
  - Beside configuration files (such as toolchains), profiles can also provide Python plugins
    for repository services.
- rbbuild source code has a new home: <https://github.com/boschglobal/rbbuild/>.
  The material in this repository is published under MIT License.


# Older versions

Changes from older versions are found in [CHANGELOG-rbbuild5.md](documentation/archive/CHANGELOG-rbbuild5.md).
