<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# Versioning and Artifactory Mapping

Artifactory channels have the following repository layout:

```
<channel root path>
    |
    +- package_name
        |
        +- 1.0.0.0-master
        +- 1.0.1.1-develop
        +- 1.0.1.2-PROJECT-1234
            |
            +- package_name-1.0.1.2-linux-native-manifest.json
            +- package_name-1.0.1.2-linux-native-sbom.cdx.json
            +- package_name-1.0.1.2-linux-native-dev.tar.xz
            +- package_name-1.0.1.2-linux-native-runtime.tar.xz
            +- package_name-1.0.1.2-win32-visualstudio-2022-manifest.json
            +- package_name-1.0.1.2-win32-visualstudio-2022-sbom.cdx.json
            +- package_name-1.0.1.2-win32-visualstudio-2022-dev.tar.xz
            +- package_name-1.0.1.2-win32-visualstudio-2022-runtime.tar.xz
```

## Version folders

rbbuild versions have the following syntax: `<major>.<minor>.<revision>.<build>-<branch>`
* major: user-defined via pyproject.toml
* minor: user-defined via pyproject.toml
* revision: automatic (days since 2018-04-16)
* build: build number from CI (0 for local builds)

The version is internally mapped to the Python packaging version scheme with four digits (PEP 440).

For branch names from Jira, the branch is always abbreviated, e.g., `PROJECT-1234-some-text`
becomes `PROJECT-1234`. Special characters, except `-`, are converted to underscores.

On `rbbuild --publish`, if the version already exists on the channel
(`VersionConflictError`), a 5th digit is appended (`.1`, incremented on
repeated conflicts) and the package is repackaged/republished under the new
version automatically.

Caveat: the repackage step re-runs `rbbuild -p`, but for CMake/pypa/npm-based
packages, component filenames and any version baked into generated C/C++
headers still reflect the original 4-digit version (set at CMake-configure
time, not from the bumped version). `manifest.json` still references those
files correctly. This is not a problem: the first 4 digits already identify
the build uniquely, the 5th digit only disambiguates the channel upload.


## Folder contents

In this folder, all files have this form:
`<package_name>-<version>-<toolchain>-<component>.<suffix>`.
The breakdown for each item is as follows:
* `package_name`: name of the package. Must match the grand-parent folder name.
* `version`: version of the package without branch. Must match parent folder name.
* `toolchain`: toolchain with the platform as first part and an identifier. Omitted for
  packages that do not depend on a toolchain (see below).
* `component`: unique package component identifier.
* `suffix`: file suffix (tar.xz by default).

There are three special components:
1. manifest.json: this is the rbbuild description file of a package and must be present.
2. sbom.cdx.json: CycloneDX SBOM file. Used for consumption in DependencyTrack and other systems.
3. "default" component: the default component is used for packages with a single component.

## Packages without toolchain

A toolchain is only selected by default if an active build tool needs one. Currently, this is
CMake (`CMakeLists.txt` is present and `cmake` is in `build-tools`). Otherwise, the
toolchain `none-any` is selected: the `obj` and `staging` folders are `obj/none-any` and
`staging/none-any`, and the package does not record a toolchain, neither in the file names nor
in manifest.json. Such packages, e.g., pure Python packages, are named
`<package_name>-<version>-<component>.<suffix>` and `<package_name>-<version>-manifest.json`.

The selected toolchain is the toolchain of the package. A toolchain is selected explicitly with
`-t` or `RBB_TOOLCHAIN_ID`. A project without toolchain, e.g., a Jenkins build with
`toolchains = ['none-any']` in the Jenkinsfile, has to select `none-any` explicitly.

A dependency without `toolchain=` is searched for the toolchain that is selected explicitly or,
if there is none, for the default toolchain of the profile for the platform (e.g., `linux-native`),
also if the project itself has no toolchain (`none-any`). With an explicit `none-any`, only manifests
without toolchain are searched. In all cases, the manifest of that toolchain is searched
first, and the manifest without toolchain is the fallback.
Packages without toolchain are compatible with every toolchain; the resolver traverses them
for any toolchain.


# Dependency Resolution Algorithm

*rbbuild* features a version resolution and conflict detection algorithm.
Consider the following example:

```
{
     "/": {
          "deps": [
              "nng_cxx",
              "nng"
          ]
     }
}
```

Let's assume the following versions exist for both packages:

```
nng_cxx-1.1.1541-master.74
nng_cxx-1.1.1334-master.72

nng-1.5.1541-master.36
nng-1.1.1334-master.34
```


Since `nng` is a dependency of `nng_cxx`, the derived version of `nng` is
directly coupled to the (resolved) version of `nng_cxx`.
Specifically, `nng_cxx-1.1.1334-master.72` depends on `nng-1.1.1334-master.34`
and `nng_cxx-1.1.1541-master.74` depends on `nng-1.5.1541-master.36`.
The third version digit indicates that both packages were built on the same day.

Let's assume, our application needs to fix `nng` to the older 1.1 version.

```
{
     "/": {
          "deps": [
              "nng_cxx",
              "nng-1.1.1334-master.34"
          ]
     }
}
```

In this case, the resolution algorithm must resolve `nng_cxx` to the older
`1.1.1334-master.72` version instead of the latest version.

The other way round, fixing `nng_cxx` to an older version, will have the
same effect:

```
{
     "/": {
          "deps": [
              "nng_cxx-1.1.1334-master.72",
              "nng"
          ]
     }
}
```

## Algorithm

The basic idea of the resolution algorithm is a depth-first walk of the tree,
while successively adding packages to a flat list of "resolved" list.
It shall be noted here, that any dependency of a package consists of
a list of packages with a fixed version. The default resolution of a package
is the latest matching version.

Input: let `entries` be a list of `Entry` objects (top-level dependency packages).
Output: `packages`: a dictionary of resolved `Package` objects, identified by
`[<installdir>/]<pkgname>[@<toolchain>]` (the version is not part of the
identifier, a package is resolved to exactly one version), and a list of
problems (errors) and warnings.

1. Fixed-version entries are searched and registered first. They are the
   *top-level* packages and cannot be replaced by nested requirements.

2. The dependency tree of each top-level package is collected depth-first
   into the flat list. For each nested package:

   1. If it is a top-level package of a different version, the top-level
      package wins: a warning is added and the nested package (and its
      subtree) is dropped.
   2. If a package with the same identifier was collected via a build-only
      path (`build_only` or `traverse=0` somewhere on the path), a runtime
      path replaces it. This makes the result independent of the order of
      the entries.
   3. If both were collected via runtime paths and the versions differ,
      a conflict is recorded. A package that is only reachable via
      build-only paths never causes a conflict; the first one is kept.
   4. Packages with `traverse=0` are registered without their dependencies.

3. Wildcard entries are resolved last:

   1. If nested packages request a version of the wildcard entry, the highest
      requested version is pinned (a warning is added if the requested
      versions differ) and its tree is collected like in step 2.
   2. Otherwise, the candidate versions are tried from the newest to the
      oldest, until one is found whose tree does not conflict with the
      packages collected so far.

4. Packages that were collected only via build-only paths are returned with
   all their components marked `build_only`. Packages with `traverse=0` are
   returned without their dependencies, so that the manifest of the package
   being built does not pass on the cut subtree.

5. The final pass adjusts the channel of the resolved packages to
   the provided channel in the input list.


### Handling of `build_only` and `traverse` package attributes

Originally, these package attributes were applied for the complete
package. In real world use cases, the need to mark individual components
of a package became apparent. Thus, the traversal and resolution
algorithm takes these flags into account:
* `build_only`: The package is installed for the package being built, but
                not for its consumers. The flag is inherited by all packages
                that are reachable only via this package, and persisted in
                the manifest as a component attribute. Nested `build_only`
                components are not installed by the staging folder.
* `traverse`: Entries with `traverse=0` imply `build_only` and cause the
               dependencies traversal to be omitted completely. This is
               handled as a conditional check in `Resolver._collect_iter`
               before the recursive child node iteration. The flag itself is
               not persisted in the manifest: the resolver removes the
               dependencies of such packages instead. The legacy spelling
               `no_traverse` is still accepted as an alias of `traverse=0`.


# Build tools, dependency managers and packaging

The core workflow of rbbuild can be applied to various use cases with
different tools for each operation (reflected by rbbuild actions "-f -I -sb -p":

|                                       | fetch (-f) / install-deps (-I) | setup (-s) / build (-b)      | packaging (-p)                 | test (-T)                      |
|---------------------------------------|--------------------------------|------------------------------|--------------------------------|--------------------------------|
| UC1: C/C++ development (classic)      | (rbbuild internal)             | CMake                        | CMake                          | CMake/CTest                    |
| default / auto-detect                 | deps.json is present           | CMakeLists.txt is present    | CMakeLists.txt is present      | CMakeLists.txt is present      |
|---------------------------------------|--------------------------------|------------------------------|--------------------------------|--------------------------------|
| UC2: Pure Python                      | pip                            | setuptools                   | setuptools                     | pytest                         |
| default / auto-detect                 | pyproject.toml is present      | pyproject.toml is present    | pyproject.toml is present      | pyproject.toml is present      |
|---------------------------------------|--------------------------------|------------------------------|--------------------------------|--------------------------------|
| UC3: Pure JavaScript:                 | npm                            | npm                          | npm                            | ???                            |
| default / auto-detect                 | package.json is present        | package.json is present      | package.json is present        | package.json is present        |
|---------------------------------------|--------------------------------|------------------------------|--------------------------------|--------------------------------|
| UC4: customized configuration         | [tool.rbbuild]                 | [tool.rbbuild]               | [tool.rbbuild]                 | [tool.rbbuild]                 |
| disable auto-detect, pyproject.toml   | deps-tools = ['rbbuild']       | build-tools = ['cmake', ...] | packaging-tools = ['rbbuild']  | test-tools = ['pytest']        |
|                                       |                                |                              |                                |                                |
|                                       |                                |                              | [tool.rbbuild.packaging.mypkg] |                                |
|                                       |                                |                              | files = ['path/to/file', ...]  |                                |
|---------------------------------------|--------------------------------|------------------------------|--------------------------------|--------------------------------|


# Repository service plugins

Repository services such as Artifactory are selected by the `type` of a profile's
remote service (`[profile.services.<name>]`). Further service types can be provided by
installed packages via the entry-point group
`rbbuild.repository`:

```toml
[project.entry-points.'rbbuild.repository']
mytype = 'mypackage.myrepo:MyRepository'
```

* The entry-point name is the service `type` (e.g., `mytype`).
* The target must be a subclass of `rbbuild.service.repository.repository.Repository`.
  It is created with the keyword arguments `channel`, `cache`, `manifest`, `temp_folder`,
  `url`, `auth_method` (from `auth-method` of the remote service, `none` if undefined),
  `user`, `credentials`, `op_mode`, and `truststore` (from `truststore` of the remote
  service, `False` if undefined). Plugins must accept `truststore` and pass it to
  `Repository.__init__`; HTTP requests must be sent with `self.session` to honor it.
* Optionally, the class attribute `display_name` is shown in the GUI.
* If a profile refers to a service type that no installed package provides, rbbuild
  reports that the service type is not available.
* Built-in types (`artifactory`, `local_file_service`, `url`) cannot be replaced.

## Minimal plugin example

`mypackage/myrepo.py` (all abstract methods of `Repository` must be implemented;
here they are stubs):

```python
from pathlib import Path
from typing import Iterator, List

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.core.temp_folder import TempFolder
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.repository.local_file_storage import LocalFileStorage
from rbbuild.service.repository.repository import AuthMethod, Repository


class MyRepository(Repository):
    display_name = 'My Repository'


    def __init__(
        self,
        channel: Channel,
        cache: LocalFileStorage,
        manifest: Manifest,
        temp_folder: TempFolder,
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        op_mode: OperationMode,
        truststore: bool,
    ):
        Repository.__init__(
            self,
            channel=channel,
            cache=cache,
            manifest=manifest,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.temp_folder = temp_folder
        self.op_mode = op_mode


    def get_versions(self, name: str) -> List[str]:
        return []


    def get_package(self, pkg: Package) -> Path:
        raise LookupError(str(pkg))


    def get_component(self, pkg: Package, component: Component) -> Path:
        raise LookupError(component.filename)


    def upload_component(self, name: str, version: str, component: Component):
        raise NotImplementedError


    def delete(self, name: str, version: str) -> bool:
        return False


    def list_package_names(self, pattern: str) -> Iterator[str]:
        return iter(())


    def list_manifest_names(self, name: str, version: str) -> List[str]:
        return []


    def resource_url(self, pkg: Package) -> str:
        return f'{self.url}{pkg.name}/{pkg.version}'
```

Registration in the pyproject.toml of the providing package. For a multi-wheel
project, use the `entry-points` key of the wheel's
`[tool.rbbuild.packaging.<name>]` entry instead, see
[rbbuild.toml.md](../user-manual/rbbuild.toml.md):

```toml
[project.entry-points.'rbbuild.repository']
mytype = 'mypackage.myrepo:MyRepository'
```

A profile can then select the service by its type:

```toml
[profile.services.my_service]
type = 'mytype'
url  = 'https://myrepo.example.com/'
```


# Configuration roots (profile packages)

Profiles and remote services can be provided by installed Python packages via
the entry-point group `rbbuild.config`. Each entry points to a package
(the *configuration root*), which keeps its data inside the package folder:

```toml
[tool.rbbuild.packaging.mywheel]
type  = 'python'
files = ['mypackage']
entry-points = [
    {group = 'rbbuild.config', name = 'mypackage', value = 'mypackage'},
]
```

```
mypackage/
    |
    +- __init__.py
    |
    +- profiles/
    |    |
    |    +- *profile*/*profile*.toml, toolchains/, remote-services/
    |
    +- remote-services/
         |
         +- *service-name*.toml
```

* Profiles are collected from the system configuration (`share/rbbuild/config/profiles`), then
  the configuration roots, then the user configuration (`~/.config/rbbuild/profiles`). If a
  profile name is found more than once, the later source wins.
* Configuration roots are processed in the alphabetical order of their entry-point names.
* The `remote-services` folder of a configuration root is shared by all profiles. The profile's
  own `remote-services` folder is loaded afterwards and may override a shared service.
* The package folder is located without importing the package.
* Because the data lives inside the package, an editable installation (`pip install -e .`) uses
  the files of the source checkout directly. Data outside of packages (wheel `shared-data`)
  cannot be made editable; see the limitations of PEP 660.

