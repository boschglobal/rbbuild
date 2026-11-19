<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

The primary purpose of **pkq** (*package query*) is for querying Artifactory.
*pkq* generally expects one or more package string `<pkgstr>` as input that
is in the "deps" format.
Examples:
```
pkq mypkg --list
pkq linuxvars-3.0.0.0 --list
pkq --platform win32 "installer>1.2" --list
```

In rare cases, package names may contain `-`. In such cases, `@` may be used to
separate package name from version:
```
pkq my-package-name --list      # bad:  name=my,              version=package-name
pkq my-package-name@ --list     # good: name=my-package-name, version=None
pkq my-package-name@3.5 --list  # good: name=my-package-name, version=3.5
```

Package syntax using URL, PURL, and Python requirements syntax is allowed, too.


# pkq --list

## Mode 1: list all packages in a channel

To retrieve all available packages in a channel, the following command can
be used:

```
pkq --list
```

Without further parameters, the profile's default channel is selected. This can
be overridden as shown below:

```
pkq --list --channel rbbuild-test
```

## Mode 2: list all versions of a package

To identify available versions of packages, package deps specifiers can
be passed to pkq. For instance:


```
pkq `boost` --list
```

The output is a list of available versions of the package `boost`.
The order of the output is reverse ordered (highest version is on top).

As with deps.json files, version ranges (PEP 508) can be used as version
constraints:

```
pkq `boost<1.79.2900,>1.79.2800` --list
```

This returns only versions of `boost` between `1.79.2900` and `1.79.2800`, which is
useful when there are many versions of a package.

The `--max-query-items` option (default: 10) limits the number of versions shown:

```
pkq boost>1.79.2900 --list --max-query-items 5
```

Development packages carry a PEP 440 local version derived from the branch
(e.g., `1.2.3.4.dev1+rbbuild.1234`). The `localversion` attribute lists only
exactly matching versions:

```
pkq "mypkg localversion=rbbuild.1234" --list
```

## Mode 3: Package detail view

When an exact (pinned) version is specified with `--list`, pkq shows detailed
information about the package including the channel, artifact URL, git repository
origin, git hash, and all available toolchains:

```
pkq boost-1.79.2969-release_9_8.89 --list
```

Example output:

```
boost-1.79.2969-release_9_8.89
  channel:    sample-development
  url:        https://artifactory.service/artifactory/sample-development-local/components/boost-1.79.2969-release_9_8.89
  git repo:   ssh://git@git.service:7999/sample/boost.git
  git hash:   1fe4657cd2f22e43271227a929a9ef8be7df04c1
  toolchains:
    linux-native
    linux-yocto-armhf-2.4
    win32-visualstudio-2017-x64
    linux-yocto-armhf-4.0
    win32-visualstudio-2017
```

The currently active toolchain is listed first, highlighted in bold.


# pkq --tree

This command will display the resolved dependency tree. Some packages may
contain dependency mismatches.
Use --ignore-errors to skip such problems.

The package name and version are printed in each line following by the
toolchain (e.g., visualstudio-2017) and various dependency flags (e.g.,
`<source>`). The package is space-indented by depth of the dependency.

Each package dependency is sorted in a so-called "namespace". A namespace
can be thought as a way to structure dependencies (there is an analogy to
C++ namespaces). Most packages will not employ named namespaces, however, they
are used in a few complex build packages, such as `rootfs`.
The default namespace is empty (i.e., unnamed), therefore not displayed above.

If the namespace is named (i.e., non-empty), it will be prefixed to the package
name. For example: the string `FW/Level 0/uboot` indicates that the package uboot
is in the namespace `FW/Level 0`.


# Show package version differences

**pkq** allows to compare two versions of a package. By default, the merges relative to the previous version will be shown.
This option uses Bitbucket as primary input source. Hence, access to Bitbucket needs to be configured first.

Example:
```
pkq nng_cxx -t yocto-armhf-2.4
```

The output is this:

With `--diff-mode=commits` the output is expanded accordingly.

The parameter `--filter-changes` allows to filter the differences
by dependency change.

| `--filter-changes=<value>`   | Description                                                                                                 |
|------------------------------|-------------------------------------------------------------------------------------------------------------|
| changed                      | The dependency version is different between the compared packages.                                          |
| same                         | The dependency has the same version in the compared package versions (displayed as "no change" if enabled). |
| new                          | Dependency has been added. Note: if a package was renamed or moved, it will show up as new and deleted.     |
| deleted                      | The dependency has been removed.                                                                            |
| moved                        | The package version is the same, but namespace has moved, e.g., from FW to FW/Level 1.                      |
| all                          | Short-cut for --filter-changes=changed,same,new,deleted,moved.                                              |

The filters can be combined with comma (not working for \*). Default:
`--filter-changes=changes,new,deleted.moved`


## Display commits and git information

The parameter `--diff-mode` can be used to modify the information detail grade as shown in this table:

| `--diff-mode=<value>`        | Description                                                                                                        |
|------------------------------|--------------------------------------------------------------------------------------------------------------------|
| basic (default)              | Only basic version information about the package and its dependencies is shown.                                    |
| commits                      | Additionally, show all commits (including JIRA ticket and commit message) that have been added for each component. |
| jira                         | Add Jira ticket link information (e.g., resolves, duplicates, etc). Implies basic and commits.                     |
| git                          | Add git commit information to the output, i.e., repository, git hash and author. Implies basic and commits.        |


By default, pkq will always traverse the dependency tree of the selected package. This behavior can be suppressed by adding `--no-traverse` to the command line.


# Reverse dependency search

It is sometimes useful to know which package version is included as dependency in other packages.
With pkq, two modes of reverse searching are available.

```shell
pkq -r "boost toolchain=linux-yocto-armhf-2.4" -C sample-development install_package
```

In this example, `boost` is the package that is being searched for (`-r`). With `-C`,
the search target is specified as channel search.
Here, the channel is `sample-development`. By providing the specific package
`install_package`, the reverse search is restricted to all versions of this package only.
Adding deps constraints (e.g., `install_package>2.0,<3.0`) is also possible.

