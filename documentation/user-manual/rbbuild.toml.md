<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# rbbuild.toml

With rbbuild 6, this file has been introduced to configure a repository (or project)
centrally.

The file format is TOML 1.0 compatible, which allows great flexibility in defining
project configuration.

Furthermore, there is a close relation to `pyproject.toml` files:
* Entries from the `[project]` section are inherited without change
* rbbuild-specific configuration items can be placed in pyproject.toml, with the
  difference that rbbuild-specific section start with `[tool.rbbuild.]` or `[tool.rbfoss]`
  in pyproject.toml.


The remainder of this document specifies the details about the different sections in
rbbuild.toml.

# Specification

## [project]

The following fields in the project section are read by rbbuild:

* `name`: the project name (defaults to the git repository name if not present)
* `branch`: Sets branch name (defaults to git repository branch name, or "local")
* `version`: String consisting of major and minor version, e.g., "1.2". While
  packaging, rbbuild generates the remaining digits of the version string.
  Note: in pyproject.toml, the entry `dynamic = ['version']` is specified to allow the dynamic
  generation of version information. Using rbbuild itself, this is not necessary with rbbuild.toml.
  If version field not present, "0.0" will be set.
* `version_major`: major version digit (has higher precedence than version)
* `version_minor`: minor version digit (has higher precedence than version)
* `version_revision`: revision version digit (has higher precedence than version)
* `version_build`: build version digit (has higher precedence than version)
* `authors` and `maintainers`: List of dicts with name and email fields (same as pyproject.toml)
* `license`: License dict (same as pyproject.toml)
* `scripts`: Dict mapping command names to Python entry-point references of the form
  `module:function`. Each entry causes the installer (pip / uv) to create a
  platform-specific script wrapper in the environment's `bin` (or `Scripts` on Windows)
  directory when the wheel is installed. Example:

  ```toml
  [project.scripts]
  rbbuild      = "rbbuild.__main__:run"
  rbbconf      = "rbbuild.rbbconf:run"
  ```

* `gui-scripts`: Same as `scripts`, but registers entries under the `[gui_scripts]`
  entry-point group. On Windows the installer creates a windowed (no console window)
  executable; on other platforms the behaviour is equivalent to `scripts`. Example:

  ```toml
  [project.gui-scripts]
  myapp-ui = "myapp.gui:main"
  ```

  > **Note:** rbbuild's own build backend writes `scripts` and `gui-scripts` entries
  > into `entry_points.txt` inside the wheel's `.dist-info` directory so that
  > pip / uv can create the script wrappers on installation.


## [rbbuild]

This section maps to `[tool.rbbuild]` in pyproject.toml. The following fields are understood
by rbbuild:

* `actions`: list of actions when calling rbbuild. Default: `[setup', 'build']`.
* `build-tools`: list of build tools. Possible values: `rbbuild`, `cmake`, `pypa`, `npm`.
* `documentation-tools`: list of documentation tools. Possible values: `pandoc`, `sphinx`.
* `test-tools`: list of tools for `rbbuild -T`. Possible values: `ctest`, `pytest`.
  If not present, `ctest` runs for CMake projects and `pytest` for projects built with `pypa`.
  Set `test-tools = ['ctest', 'pytest']` to run `pytest` also in a CMake project.
* `sca-tools`: list of static code analysis tools for `rbbuild --sca`. Possible values: `ruff`.
  Default: `['ruff']`.

## [packaging.<pkgname>]

This section maps to `[tool.rbbuild.packaging]` in pyproject.toml. In this section, packages
can be specified with the following fields:

* `type`: packaging strategy. One of:
  * `auto` (default): a single matched file is used as-is (`plain` behavior below); more than
    one matched file is compressed into an archive (`archive` behavior below).
  * `plain`: uses the single matched file as-is. `files` must match exactly one file (not a
    directory). `suffix` must not be used in this case; the file extension is used as-is.
  * `archive`: always compresses all matched files into an archive, even if only one file is
    matched. `suffix` may be set to choose the archive format (default `tar.xz`).
  * `python`: handled by the pypa build backend instead of being packaged here.
* `files`: list of file entries. Each entry is either a plain string (file path or glob), or a
  dict with the following keys:
  * `src` (mandatory): file path or glob pattern
  * `strip` (optional): path prefix stripped from each matched path inside the archive. May start
    with `$OBJ/`, `$STAGING/` or `$DOCUMENTATION/` (e.g., `strip = '$OBJ/'`)
  * `dest` (optional): path prefix prepended to each archive entry
* `exclude`: list of glob patterns to exclude from files matched by `files`. Also applied
  during directory expansion inside generated wheels, so subdirectories of a directory listed
  in `files` can be excluded here (e.g. `rbbuild/data/**`). Applies to `files` only; does not
  affect `shared-data`.
* `shared-data`: list of file entries (same `src` / `strip` / `dest` dict format as `files`)
  that are placed in the wheel's `.data/data/` section instead of the purelib root. pip and uv
  install these files under `{prefix}/` on the target system, so a `dest` of `share/<pkgname>`
  causes them to land at `{prefix}/share/<pkgname>/`. Returns an empty section when absent.
  Example — keep `rbbuild/data` out of the Python package tree and install it as shared data:

  ```toml
  [tool.rbbuild.packaging.wheel]
  type    = 'python'
  files   = ['rbbuild']
  exclude = ['rbbuild/data/**']
  shared-data = [
      {src = 'rbbuild/data/**', strip = 'rbbuild/data', dest = 'share/rbbuild'},
  ]
  ```

* `suffix`: archive format, e.g., `tar.xz`, `tar.gz`, `tar.bz2`, `zip`. Only applies to
  `auto`/`archive` types producing an archive; auto-detected (default `tar.xz`) if not defined.
* `traverse` and `build-only`: rbbuild component flags
* `entry-points` (`type = 'python'` only): list of `{group, name, value}` tables added to this
  wheel's entry_points.txt, e.g.,
  `{group = 'rbbuild.repository', name = 'csi', value = 'mypkg.csi:CSI'}`. Merged with
  `[project.scripts]`, `[project.gui-scripts]`, and `[project.entry-points]`, which apply to
  all wheels of the project.
* `depends-on` (`type = 'python'` only): name (or list of names) of other `python` packaging
  entries, i.e., components of the same package, that this wheel depends on. Each is added to
  the wheel and sdist metadata as dependency pinned to the exact same version (e.g.,
  `mypkg_other==1.2.3.4`). This is only wheel metadata, it is not recorded in manifest.json,
  hence, it is enforced by pip but not by `rbbuild -I`. Using `depends-on` with any other
  type is an error.
* `platform-specific`, `wheel-tag` (`type = 'python'` only): create a wheel that
  contains compiled code (e.g., a shared library or an extension module built by CMake). By
  default, the wheel is tagged `py3-none-any`, i.e., installable on any platform.
  With `platform-specific = true`, the wheel is tagged with the platform instead
  (`Root-Is-Purelib: false`), e.g., `py3-none-linux_x86_64`:
  * The Python part of the tag is `py3-none` for code that does not use the Python C API
    (e.g., a library loaded with `ctypes`). If the wheel contains CPython extension modules, it
    is taken from their file names (e.g., `_x.cpython-312-x86_64-linux-gnu.so` or
    `_x.cp312-win_amd64.pyd` result in `cp312-cp312`). abi3 modules and extension modules
    of several Python versions are not supported.
  * The platform part is the `platform-tag` of the toolchain definition in the profile, or
    the tag of the interpreter for `native` toolchains (see [rbbconf](rbbconf.md)).
  * `wheel-tag`: sets the complete tag explicitly (e.g., `py3-none-linux_armv7l`), which is
    required for toolchains without platform tag.

  `wheel-tag` requires `platform-specific = true`. Using any of the two keys
  with another type is an error. A package with a platform-specific wheel needs a toolchain
  (`-t`, or CMake in the project), see [architecture](../developer-manual/architecture.md). See the examples
  [python-ctypes-c](../examples/python-ctypes-c/README.md) and
  [python-cext-c](../examples/python-cext-c/README.md).

The variables `$OBJ`, `$STAGING`, and `$DOCUMENTATION` may be used as file prefix paths,
pointing at `obj/<tcid>`, `staging/<tcid>`, and `obj/documentation/`, respectively.
All paths should be separated with / (also on Windows).


## [dependencies] and [[dependencies]]

This section contains the representation of dependencies (formerly defined in deps.json).

Accepted fields are:

* `deps`: list of deps entry strings (PEP 508 compatible, with space-separated attributes).
  This is the only mandatory field.
* `namespace`: Installation namespace (sub-path in staging).
* `restrict_platform`: Only apply if the platform matches (e.g., 'linux' or 'win32')
* `restrict_toolchain`: Only apply if the toolchain matches, can be a wilcard (example: 'visualstudio-????')


Section parameters apply to each component in the deps list
* `components`: list component names
* `build_only`: build-only flag
* `traverse`: traverse flag (default true; `traverse = false` stops the traversal of dependencies, `no_traverse` is accepted as alias)
* `package_install_action`: Default action for install (valid values: 'COPY').


By using double bracket ([[dependencies]]), more than one section may be defined. This allows
the definition of structured dependencies, e.g., for different namespaces, platforms, or toolchains.

If rbbuild.toml exists and contains a dependencies section, any deps or deps.json files will be
ignored.


### Examples

Basic example with section parameters components and build_only set:

```
[dependencies]
deps = [
    'pkg1',
    'pkg2>2.0.0',
    'pkg3 components=prod',
]
components = "prod licences"
build_only = 1
```

Double-bracket example with different namespaces:

```
[[dependencies]]
deps = [...]
namespace = 'my_namespace_name'

[[dependencies]]
deps = [...]
```

Double-bracket example with different platforms and toolchains:

```
[[dependencies]]
deps = [...]
restrict_platform = 'linux'

[[dependencies]]
deps = [...]
restrict_toolchain = 'visualstudio-2022'
```


### Dependency Entry Format

Each entry in a `deps` list is a space-separated string:

```
[<channel>:]<pkg>[-<version>|@<version>|@] [<attr> ...]

with:
  <channel>   -- Channel name (must not contain whitespace)
  <pkg>       -- Package name (must not contain whitespace)
  <version>   -- Exact version or PEP 508 constraint
  <attr>      -- Flag (<key> or <key>=<value>)
```

Examples:
* `zlib` — latest available version
* `zlib-1.3.1` — exact version
* `my-lib@2.4` — exact version for package names containing `-`
* `my-lib@` — latest version for package names containing `-`
* `sample-sources:zlib<1.3` — latest version satisfying the constraint, from a specific channel
* `pkg:generic/zlib@1.3.1` — PackageURL form
* `https://example.org/mypkg-1.2.3.4.tar.gz` — plain URL
* `zlib-1.3.1 build_only components=prod` — with flags


### Configuration Flags

Each dependency entry can carry one or more *configuration flags*:

| Flag | Description | Example |
|---|---|---|
| `component(s)` | One or more sub-components to be processed. If not specified, all components are selected. The component `default` is treated specially: it will not generate a subcomponent part in the resulting file string. | `components=default`<br>`components=licenses,dev` |
| `suffix(es)` | One or more file suffixes to be processed. | `suffix=tar.xz`<br>`suffixes=rpm,tar.gz` |
| `build_only` | Marks the package as build-time-only. It and its transitive dependencies are installed for your own build, but are not installed by consumers of your package. See [Dependency Resolution](#dependency-resolution). | `build_only` |
| `traverse` | Defaults to `1`. With `traverse=0`, the package itself is installed, but none of its transitive dependencies are resolved, installed or passed on to consumers. Implies `build_only`. Use this when the transitive dependencies are irrelevant or provided by other means. `no_traverse` is still accepted as an alias of `traverse=0`; specifying both with contradicting values is an error. | `traverse=0` |
| `installdir` | Installation directory relative to `staging/<tcid>` when using `rbbuild -I`. Defaults to the namespace name. | `installdir=licenses` |
| `package_install_action` | Overrides the default install action. Available values: `copy` (copy file as-is into `installdir`). Default behavior: archive formats (`tar.gz`, `zip`, …) are extracted; `rpm` and `sha512` files are ignored. | `package_install_action=copy` |
| `localversion` | Only versions whose PEP 440 local segment (the part after `+`) matches exactly are considered, e.g., development packages built from a ticket branch. Combinable with version constraints. Development versions (`.devN`) sort below their release, so `>=1.2.3.4` does not match `1.2.3.4.dev1+rbbuild.1234`. | `localversion=rbbuild.1234` |


### Dependency Resolution

The packages listed in `deps` are the *top-level* entries; everything they
depend on is *nested*. A package is resolved to exactly one version.

1. Top-level entries decide the versions. A nested requirement is never
   stronger than a top-level entry.
2. If a nested requirement differs from a top-level entry, the top-level entry
   wins and a warning is printed.
3. A top-level entry without a version adopts the version requested by the
   nested requirements. If they request different versions, the highest one is
   used and a warning is printed.
4. Two nested requirements for different versions of the same package are an
   error, unless one of them is `build_only` or `traverse=0`.
5. Listing the same package twice at the top level is an error.
6. A `traverse=0` package is installed without its dependencies, and its
   dependencies are not passed on to consumers.
7. A package that is `build_only` only on some paths is installed for
   consumers if at least one runtime path leads to it. Its version is taken
   from the runtime path, regardless of the order of the entries.
8. Nested `build_only` components are not installed. For top-level entries, all
   selected components are installed; the `build_only` flag is passed on to
   consumers.

Examples (`A->B-1.0` means that `A` requires `B-1.0`):

| Top level | Nested | Result |
|---|---|---|
| `A`, `B-2.0` | `A->B-1.0` | `B-2.0`, with a warning |
| `A`, `B` | `A->B-1.0` | `B-1.0` |
| `A`, `B` | `A->C-1.0`, `B->C-2.0` | Error: conflicting nested versions of `C` |
| `A`, `B`, `C` | `A->C-1.0`, `B->C-2.0` | `C-2.0` (highest), with a warning; with `C-3.0` at the top level: `C-3.0`, with warnings |
| `A build_only`, `X` | `A->B-2.0`, `X->B-1.0` | `B-1.0` for both orders of entries; `B` is installed for consumers |
| `A build_only` | `A->B-1.0` | `B` is installed for you, but not for consumers |
| `A traverse=0` | `A->B-1.0` | Only `A` is installed; consumers do not see `B` |


### Version Syntax and Variable Substitution

All version strings follow [PEP 508](https://www.python.org/dev/peps/pep-0508/) semantics.

**Exact pinning:**

| Form | Example | Notes |
|---|---|---|
| Canonical 4-digit | `mypkg-1.2.3.4` | Preferred format |
| `@`-separator | `my-package-name@1.2.3.4` | Recommended when the package name contains `-` or spaces |
| PackageURL | `pkg:generic/mypkg@1.2.3.4` | |
| URL | `https://example.org/mypkg-1.2.3.4.tar.gz` | Generic download |
| Legacy | `mypkg-1.2.3-master.4` | Deprecated; only allowed for exact pins, not ranges |

**Ranges and constraints:**

| Form | Example |
|---|---|
| Latest available | `mypkg` or `my-package-name@` |
| Inequality | `mypkg>=1.2.0,<2.0.0` |
| Compatible release | `mypkg~=1.2.0` |
| Wildcard | `mypkg==1.2.*` |
| Exclusion | `mypkg!=1.2.3.4` |
| Channel-prefixed | `sample-sources:mypkg>=1.2.0` |

> **Note:** Version ranges are significantly slower to resolve than exact pins.

**Variable substitution:**

Version strings may contain `$PACKAGE_*` variables, substituted at resolve time:

| Variable | Description |
|---|---|
| `$PACKAGE_VERSION` | Full version string, e.g. `9.0.123.4` |
| `$PACKAGE_NAME` | Package name |
| `$PACKAGE_MAJOR` | Major version digit |
| `$PACKAGE_MINOR` | Minor version digit |
| `$PACKAGE_REVISION` | Revision digit |
| `$PACKAGE_BUILD` | Build number |

This feature is useful when package and dependency versions must be aligned.
Example: `mydep-$PACKAGE_VERSION` resolves to the same version as the current package, e.g., `mydep-1.2.3.4`.


## [oss]

Settings to configure rbfoss. The following fields are parsed:

* `users`: List of assigned owners
* `exclude_dependencies`: List of packages that will be excluded from dependency check
* `ignore_files`: List of files that will be excluded from scanning
* `ignore_folders`: List of folders that will be excluded from scanning
* `ignore_extensions`: List of files with specified extensions that will be excluded from scanning

As of now, all fields are specific for FossID.


### Example

```
[oss]
users = ['jdoe']
exclude_dependencies = ['build_tools', 'sign_supplicant-1.2.3.4']
ignore_extensions = ['ism']
ignore_folders = ['unit_test', 'component_test', '.git']
ignore_files = ['.gitignore']
```

## [cmake]

CMake-specific parameters are configured in this section.

* `cmake_defines`: List of key-value parameters that are passed as `cmake -D key=value`


## [pandoc.<document-name>]

This section contains pandoc-specific settings for a document. Accepted fields:
* `files`: List of files (Python globs are allowed)


## [sphinx.<document-name>]

This section contains Sphinx-specific settings for a document. Accepted fields:
* `sourcedir`: Path to the Sphinx RST files
* `title`: document title
* `logo`: Path to an image that is taken as logo
* `generate_changelog`: List of Jira search strings for retrieving the changelogs (see pkq)

