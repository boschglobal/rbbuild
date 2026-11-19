# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re

from packaging.version import InvalidVersion, Version


# The following method is used as sort key for version searches (e.g., pkq -l).
# Normalizes 'major.minor.patch-branch.build' to 'major.minor.patch.build'
# so the build counter sorts numerically regardless of branch name.
# Integers sort before strings so mixed version schemes never raise TypeError.
def version_sort_function(ver: str) -> list:
    ver = re.sub(r'(\d+\.\d+\.\d+)-[\w\d-]+\.(\d+)', r'\1.\2', ver)
    items = []
    for part in re.split(r'[\.\-\+]', ver):
        try:
            items.append((0, int(part)))    # (0, n) — integers sort before strings
        except ValueError:
            items.append((1, part))         # (1, s) — strings sort after integers
    return items


# Exact match of the PEP 440 local version segment (the part after '+').
# PEP 440 normalizes the segment to lowercase with '.' as separator.
def matches_localversion(version: str, localversion: str) -> bool:
    try:
        local = Version(version).local
    except InvalidVersion:
        return False
    return local == re.sub(r'[-_]', '.', localversion.lower())


# Join path segments, skipping empty parts (e.g. an optional root_path)
def build_path(*parts: str) -> str:
    return '/'.join(p for p in parts if p)


# Retry version for rbbuild --publish version conflicts: rbbuild versions
# have 4 numeric release components (major.minor.revision.build). Appends a
# 5th component starting at 1, or increments it if already present, e.g.:
#   1.2.3.4      -> 1.2.3.4.1
#   1.2.3.4.1    -> 1.2.3.4.2
# Any dev/local suffix (e.g. '.devN+branch' for development channels) is
# preserved as-is.
def bump_conflict_version(version: str) -> str:
    v = Version(version)
    release = list(v.release)
    if len(release) < 5:
        release += [0] * (4 - len(release)) + [1]
    else:
        release[4] += 1

    result = '.'.join(str(p) for p in release)
    if v.dev is not None:
        result += f'.dev{v.dev}'
    if v.local:
        result += f'+{v.local}'
    return result

