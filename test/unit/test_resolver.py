# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch

from rbbuild.package.component import Component
from rbbuild.package.package import Package
from rbbuild.resolver.resolver import Resolver


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pkg(name, version='', toolchain=None, build_only=False, traverse=True):
    p = Package(name=name, version=version)
    if toolchain is not None:
        p.toolchain = toolchain
    if build_only or not traverse:
        comp = Component(name=name, suffix='dev', build_only=build_only, traverse=traverse)
        p.components = [comp]
    else:
        # A package with no components reports build_only=True, which is fine
        # for most tests; when we need build_only=False explicitly, we add a comp.
        comp = Component(name=name, suffix='dev', build_only=False)
        p.components = [comp]
    return p


def _deps(*packages) -> dict:
    return {repr(p): p for p in packages}


def _make_resolver(search_results=(), verbose=False):
    repoman = MagicMock()
    repoman.search.side_effect = iter(search_results)
    return Resolver(repoman=repoman, op_mode=MagicMock(verbose=verbose))


# Return a Resolver whose repoman.search() yields successive lists of packages.
def _resolver(*search_results):
    return _make_resolver(search_results)


# ---------------------------------------------------------------------------
# run() — fixed versions
# ---------------------------------------------------------------------------

# A single package with an exact version resolves to itself.
def test_run_fixed_single():
    pkg_in  = _pkg('nng', '1.0.0')
    pkg_out = _pkg('nng', '1.0.0')

    resolver = _resolver([pkg_out])
    result = resolver.run({'nng': pkg_in}, transitive=False)

    assert not result.problems
    assert repr(pkg_in) in result.packages
    assert result.packages[repr(pkg_in)] is pkg_out


# When no match is found for a fixed version, it's reported in `problems`
# instead of raising - and does not prevent the rest of the run() call.
def test_run_fixed_not_found():
    pkg_in = _pkg('nng', '1.0.0')

    resolver = _resolver([])   # search returns nothing
    result = resolver.run({'nng': pkg_in}, transitive=False)

    assert result.packages == {}
    assert len(result.problems) == 1
    assert 'Could not resolve' in result.problems[0]


# Multiple fixed-version inputs are each resolved independently.
def test_run_fixed_multiple():
    a_in  = _pkg('nng', '1.0.0')
    b_in  = _pkg('curl', '8.0.0')
    a_out = _pkg('nng', '1.0.0')
    b_out = _pkg('curl', '8.0.0')

    resolver = _resolver([a_out], [b_out])
    result = resolver.run({repr(a_in): a_in, repr(b_in): b_in}, transitive=False)

    assert not result.problems
    assert repr(a_in) in result.packages
    assert repr(b_in) in result.packages


# A fixed-version entry that cannot be resolved does not stop the remaining
# entries from being processed - both the problem and the successful entry
# are reflected in the result.
def test_run_fixed_one_not_found_others_still_processed():
    a_in  = _pkg('nng', '1.0.0')
    b_in  = _pkg('curl', '8.0.0')
    b_out = _pkg('curl', '8.0.0')

    resolver = _resolver([], [b_out])   # 'nng' search misses, 'curl' search hits
    result = resolver.run({repr(a_in): a_in, repr(b_in): b_in}, transitive=False)

    assert repr(b_in) in result.packages
    assert len(result.problems) == 1
    assert 'Could not resolve' in result.problems[0]


# ---------------------------------------------------------------------------
# run() — transitive flag
# ---------------------------------------------------------------------------

# transitive=False returns only top-level packages, not their children.
def test_run_transitive_false():
    child = _pkg('openssl', '3.0.0')
    parent = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    resolver = _resolver([parent])
    result = resolver.run({repr(parent): parent}, transitive=False)

    assert repr(parent) in result.packages
    assert repr(child) not in result.packages


# transitive=True returns top-level packages AND all transitive children.
def test_run_transitive_true():
    child = _pkg('openssl', '3.0.0')
    parent = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    resolver = _resolver([parent])
    result = resolver.run({repr(parent): parent}, transitive=True)

    assert repr(parent) in result.packages
    assert repr(child) in result.packages


# ---------------------------------------------------------------------------
# run() — wildcard versions
# ---------------------------------------------------------------------------

# A package without a version string is treated as a wildcard; the resolver
# picks the first candidate from repoman.search().
def test_run_wildcard_resolved():
    pkg_in  = _pkg('nng', '')      # no version = wildcard
    pkg_out = _pkg('nng', '1.5.0')

    resolver = _resolver([pkg_out])
    result = resolver.run({repr(pkg_in): pkg_in}, transitive=False)

    assert not result.problems
    assert result.packages[repr(pkg_in)] is pkg_out


# A wildcard package is skipped if it was already transitively pulled in.
def test_run_wildcard_already_collected():
    child   = _pkg('openssl', '3.0.0')
    parent  = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    pkg_wild = _pkg('openssl', '')   # wildcard for openssl

    resolver = _resolver([parent])   # only one search call expected (for curl)
    result = resolver.run(
        {repr(parent): parent, repr(pkg_wild): pkg_wild},
        transitive=True,
    )

    # curl was resolved from a fixed version, dragging openssl in transitively;
    # the wildcard openssl entry should be satisfied without an extra search call
    assert repr(child) in result.packages


# When transitive=False the wildcard package must still appear in the result even
# though it was satisfied via the already-collected path (no extra search call).
# BUG T2: the continue statement fires before packages[repr(pkg_in)] = pkg is
# ever executed, so the entry is silently absent from the non-transitive result.
def test_run_wildcard_already_collected_transitive_false():
    child   = _pkg('openssl', '3.0.0')
    parent  = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    pkg_wild = _pkg('openssl', '')   # wildcard for openssl

    resolver = _resolver([parent])   # search called once (for curl), not for openssl
    result = resolver.run(
        {repr(parent): parent, repr(pkg_wild): pkg_wild},
        transitive=False,
    )

    # curl is a fixed top-level package → must be present
    assert repr(parent) in result.packages
    # openssl came in via transitive pull from curl; the wildcard entry for it
    # must also appear in the non-transitive result
    assert repr(pkg_wild) in result.packages


# A wildcard already collected whose version satisfies the requester's constraints
# is accepted without error (no extra search call needed).
def test_run_wildcard_already_collected_constraint_satisfied():
    child  = _pkg('openssl', '3.1.0')
    parent = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    pkg_wild = _pkg('openssl', '')
    pkg_wild.version_constraints = '>=3.0'   # 3.1.0 satisfies >=3.0

    resolver = _resolver([parent])
    result = resolver.run(
        {repr(parent): parent, repr(pkg_wild): pkg_wild},
        transitive=True,
    )

    assert not result.problems
    assert repr(child) in result.packages


# A wildcard already collected whose version violates the requester's constraints
# is reported in `problems` instead of raising.
def test_run_wildcard_already_collected_constraint_violated():
    child  = _pkg('openssl', '2.0.0')
    parent = _pkg('curl', '8.0.0')
    parent.dependencies = _deps(child)

    pkg_wild = _pkg('openssl', '')
    pkg_wild.version_constraints = '>=3.0'   # 2.0.0 does NOT satisfy >=3.0

    resolver = _resolver([parent])
    result = resolver.run(
        {repr(parent): parent, repr(pkg_wild): pkg_wild},
        transitive=False,
    )

    assert len(result.problems) == 1
    assert 'Version conflict' in result.problems[0]
    assert repr(pkg_wild) not in result.packages


# No wildcard candidate is conflict-free → reported in `problems`.
def test_run_wildcard_no_candidate():
    # First, fix-resolve curl which pulls in openssl-3.0.0 transitively.
    openssl3 = _pkg('openssl', '3.0.0')
    curl = _pkg('curl', '8.0.0')
    curl.dependencies = _deps(openssl3)

    # The only wildcard candidate for 'libfoo' depends on openssl-2.0.0,
    # conflicting with the already-collected openssl-3.0.0.
    openssl2 = _pkg('openssl', '2.0.0')
    libfoo_candidate = _pkg('libfoo', '1.0')
    libfoo_candidate.dependencies = _deps(openssl2)

    pkg_wild = _pkg('libfoo', '')   # wildcard for libfoo

    resolver = _resolver([curl], [libfoo_candidate])
    result = resolver.run(
        {repr(curl): curl, repr(pkg_wild): pkg_wild},
        transitive=True,
    )

    assert len(result.problems) == 1
    assert 'Could not resolve' in result.problems[0]
    assert repr(pkg_wild) not in result.packages


# A wildcard candidate whose own subtree has an internal version conflict
# (unrelated to already-collected packages) is rejected just like a candidate
# that conflicts externally - the next candidate is tried instead.
def test_run_wildcard_candidate_with_internal_conflict_is_rejected():
    # First candidate for 'libfoo' has an internal conflict: two deps named
    # 'openssl' at different, non-build_only versions.
    openssl_a = _pkg('openssl', '1.0.0')
    openssl_b = _pkg('openssl', '2.0.0')
    sub_a = _pkg('sub_a', '1.0')
    sub_a.dependencies = _deps(openssl_a)
    sub_b = _pkg('sub_b', '1.0')
    sub_b.dependencies = _deps(openssl_b)
    bad_candidate = _pkg('libfoo', '1.0')
    bad_candidate.dependencies = _deps(sub_a, sub_b)

    # Second candidate is conflict-free.
    good_candidate = _pkg('libfoo', '2.0')

    pkg_wild = _pkg('libfoo', '')

    resolver = _resolver([bad_candidate, good_candidate])
    result = resolver.run({repr(pkg_wild): pkg_wild}, transitive=True)

    assert not result.problems
    assert result.packages[repr(pkg_wild)] is good_candidate


# Two transitive build_only deps at different versions must not block a wildcard
# candidate — this is the reported bug.
def test_run_wildcard_build_only_transitive_no_conflict():
    gtest_v1 = _pkg('gtest', '1.0', build_only=True)
    pkg_a = _pkg('pkg_a', '1.0')
    pkg_a.dependencies = _deps(gtest_v1)

    gtest_v2 = _pkg('gtest', '2.0', build_only=True)
    pkg_b_candidate = _pkg('pkg_b', '2.0')
    pkg_b_candidate.dependencies = _deps(gtest_v2)

    pkg_b_wild = _pkg('pkg_b', '')

    resolver = _resolver([pkg_a], [pkg_b_candidate])
    result = resolver.run(
        {repr(pkg_a): pkg_a, repr(pkg_b_wild): pkg_b_wild},
        transitive=True,
    )

    assert not result.problems
    assert repr(pkg_b_wild) in result.packages
    assert result.packages[repr(pkg_b_wild)] is pkg_b_candidate


# Same as above, but with traverse=False instead of build_only.
def test_run_wildcard_traverse_false_transitive_no_conflict():
    cmake_v1 = _pkg('cmake', '3.25', traverse=False)
    pkg_a = _pkg('pkg_a', '1.0')
    pkg_a.dependencies = _deps(cmake_v1)

    cmake_v2 = _pkg('cmake', '3.26', traverse=False)
    pkg_b_candidate = _pkg('pkg_b', '2.0')
    pkg_b_candidate.dependencies = _deps(cmake_v2)

    pkg_b_wild = _pkg('pkg_b', '')

    resolver = _resolver([pkg_a], [pkg_b_candidate])
    result = resolver.run(
        {repr(pkg_a): pkg_a, repr(pkg_b_wild): pkg_b_wild},
        transitive=True,
    )

    assert not result.problems
    assert repr(pkg_b_wild) in result.packages
    assert result.packages[repr(pkg_b_wild)] is pkg_b_candidate


# ---------------------------------------------------------------------------
# collect() — basic traversal
# ---------------------------------------------------------------------------

# A leaf package (no dependencies) collects only itself.
def test_collect_single_leaf():
    nng = _pkg('nng', '1.0.0')
    resolver = _make_resolver()
    result = resolver.collect(this=nng, pkg_in=nng)
    assert not result.conflicts
    assert repr(nng) in result.packages


# A tree of A → B → C is fully collected.
def test_collect_transitive_depth():
    c = _pkg('c', '1.0')
    b = _pkg('b', '1.0')
    b.dependencies = _deps(c)
    a = _pkg('a', '1.0')
    a.dependencies = _deps(b)

    resolver = _make_resolver()
    result = resolver.collect(this=a, pkg_in=a)

    assert repr(a) in result.packages
    assert repr(b) in result.packages
    assert repr(c) in result.packages


# Visiting the same package at the same version twice does not duplicate or raise.
def test_collect_deduplicated():
    shared = _pkg('shared', '1.0')
    left   = _pkg('left',   '1.0')
    right  = _pkg('right',  '1.0')
    left.dependencies  = _deps(shared)
    right.dependencies = _deps(shared)
    root = _pkg('root', '1.0')
    root.dependencies = _deps(left, right)

    resolver = _make_resolver()
    result = resolver.collect(this=root, pkg_in=root)

    # shared appears only once
    assert list(result.packages.values()).count(shared) == 1


# Two different packages that share a name but have conflicting versions are
# reported in `conflicts` instead of raising.
def test_collect_version_conflict_recorded():
    v1 = _pkg('openssl', '1.0.0')
    v2 = _pkg('openssl', '2.0.0')   # same name, different version
    v2.components[0].build_only = False

    root = _pkg('root', '1.0')
    root.dependencies = _deps(v1)

    # manually inject a pre-existing entry so collect() sees the conflict
    existing = {repr(v1): v2}   # key matches v1 repr but value has different version

    resolver = _make_resolver()
    result = resolver.collect(this=v1, pkg_in=v1, packages=existing)

    assert repr(v1) in result.conflicts
    assert 'Version conflict' in result.conflicts[repr(v1)]


# A package with traverse=False at a different version must not be recorded as a
# conflict — mirrors the existing build_only suppression.
def test_collect_traverse_false_version_conflict_suppressed():
    v1 = _pkg('cmake', '3.25.0', traverse=False)
    v2 = _pkg('cmake', '3.26.0', traverse=False)

    existing = {repr(v1): v1}

    resolver = _make_resolver()
    result = resolver.collect(this=v2, pkg_in=v2, packages=existing)
    assert not result.conflicts
    assert result.packages[repr(v1)] is v1


# ---------------------------------------------------------------------------
# collect() — passing an existing `conflicts` dict to accumulate across calls
# ---------------------------------------------------------------------------

# A version conflict is recorded in `conflicts`, keyed like `packages`.
def test_collect_records_conflict_into_passed_in_dict():
    v1 = _pkg('openssl', '1.0.0')
    v2 = _pkg('openssl', '2.0.0')   # same name, different version
    v2.components[0].build_only = False

    root = _pkg('root', '1.0')
    root.dependencies = _deps(v1)

    existing = {repr(v1): v2}   # key matches v1 repr but value has different version

    resolver = _make_resolver()
    conflicts = {}
    result = resolver.collect(this=v1, pkg_in=v1, packages=existing, conflicts=conflicts)

    assert result.conflicts is conflicts
    assert repr(v1) in conflicts
    assert 'Version conflict' in conflicts[repr(v1)]
    # first-seen (v2, injected via `existing`) is kept
    assert result.packages[repr(v1)] is v2


# ---------------------------------------------------------------------------
# collect() — skip_build_only
# ---------------------------------------------------------------------------

# With skip_build_only=True, children flagged build_only are not traversed.
def test_collect_skip_build_only_child():
    build_dep = _pkg('gtest', '1.9.0', build_only=True)
    runtime_dep = _pkg('openssl', '3.0.0', build_only=False)
    root = _pkg('mylib', '1.0')
    root.dependencies = _deps(build_dep, runtime_dep)

    resolver = _make_resolver()
    result = resolver.collect(this=root, pkg_in=root, skip_build_only=True)

    assert repr(root) in result.packages
    assert repr(runtime_dep) in result.packages
    assert repr(build_dep) not in result.packages


# With skip_build_only=False (default), build_only deps are included.
def test_collect_includes_build_only_by_default():
    build_dep = _pkg('gtest', '1.9.0', build_only=True)
    root = _pkg('mylib', '1.0')
    root.dependencies = _deps(build_dep)

    resolver = _make_resolver()
    result = resolver.collect(this=root, pkg_in=root, skip_build_only=False)

    assert repr(build_dep) in result.packages


# A child with traverse=False is excluded when skip_build_only is True.
def test_collect_skip_traverse_false():
    no_trav = _pkg('gtest', '1.9.0', traverse=False)
    root = _pkg('mylib', '1.0')
    root.dependencies = _deps(no_trav)

    resolver = _make_resolver()
    result = resolver.collect(this=root, pkg_in=root, skip_build_only=True)

    assert repr(no_trav) not in result.packages


# A traverse=False package that is itself collected must not have its own
# transitive dependencies traversed.
def test_collect_traverse_false_stops_child_traversal():
    grandchild = _pkg('openssl', '3.0')
    no_trav = _pkg('installer', '9.7', traverse=False)
    no_trav.dependencies = _deps(grandchild)

    resolver = _make_resolver()
    # The traverse=False package itself must appear, but its child must not.
    result = resolver.collect(this=no_trav, pkg_in=no_trav)

    assert repr(no_trav) in result.packages
    assert repr(grandchild) not in result.packages


# ---------------------------------------------------------------------------
# collect() — toolchain cross-dependency skipping
# ---------------------------------------------------------------------------

# Transitive deps with no installdir inherit the installdir from pkg_in context.
def test_collect_propagates_installdir():
    child = _pkg('nng', '1.0')

    parent = _pkg('mypkg', '2.0')
    parent.installdir = 'x64'
    parent.dependencies = _deps(child)

    resolver = _make_resolver()
    result = resolver.collect(this=parent, pkg_in=parent)

    # parent was already x64 — key unchanged
    assert repr(parent) in result.packages
    # child had no installdir; it must inherit x64 and appear under that prefix
    nng_key = next((k for k in result.packages if 'nng' in k), None)
    assert nng_key is not None
    assert result.packages[nng_key].installdir == 'x64'
    assert nng_key.startswith('x64/')


# A child that already has its own installdir must not have it overwritten.
def test_collect_does_not_overwrite_existing_installdir():
    child = _pkg('rootfs', '1.0')
    child.installdir = 'FW'

    parent = _pkg('mypkg', '2.0')
    parent.installdir = 'x64'
    parent.dependencies = _deps(child)

    resolver = _make_resolver()
    result = resolver.collect(this=parent, pkg_in=parent)

    fw_key = next((k for k in result.packages if 'rootfs' in k), None)
    assert fw_key is not None
    assert result.packages[fw_key].installdir == 'FW'
    assert fw_key.startswith('FW/')


# A dependency built for a different toolchain is not traversed.
def test_collect_skips_foreign_toolchain():
    tc_linux = MagicMock()
    tc_linux.__repr__ = lambda _: 'linux-native'
    tc_linux.platform = 'linux'
    tc_win32 = MagicMock()
    tc_win32.__repr__ = lambda _: 'win32-mingw'
    tc_win32.platform = 'win32'

    win_dep = _pkg('msvc_helper', '1.0')
    win_dep.toolchain = tc_win32

    root = _pkg('mylib', '1.0')
    root.toolchain = tc_linux
    root.dependencies = _deps(win_dep)

    resolver = _make_resolver()
    result = resolver.collect(this=root, pkg_in=root)

    # win_dep is from a different platform and must not appear
    assert repr(win_dep) not in result.packages


# A dep with the same platform but a different toolchain version must NOT be skipped.
# Example: installer@win32-visualstudio-2017-x64 depends on
# generator@win32-visualstudio-2022; both are Windows packages.
def test_collect_same_platform_different_toolchain_version_not_skipped():
    tc_vs2017 = MagicMock()
    tc_vs2017.__repr__ = lambda _: 'Toolchain(win32, visualstudio-2017-x64)'
    tc_vs2017.__str__  = lambda _: 'win32-visualstudio-2017-x64'
    tc_vs2017.__bool__ = lambda _: True
    tc_vs2017.platform = 'win32'

    tc_vs2022 = MagicMock()
    tc_vs2022.__repr__ = lambda _: 'Toolchain(win32, visualstudio-2022)'
    tc_vs2022.__str__  = lambda _: 'win32-visualstudio-2022'
    tc_vs2022.__bool__ = lambda _: True
    tc_vs2022.platform = 'win32'

    generator = _pkg('generator', '5.0')
    generator.toolchain = tc_vs2022

    installer = _pkg('installer', '9.7', build_only=True)
    installer.toolchain = tc_vs2017
    installer.dependencies = _deps(generator)

    resolver = _make_resolver()
    result = resolver.collect(this=installer, pkg_in=installer)

    # generator is a same-platform dep and must appear in the result
    assert repr(generator) in result.packages


# ---------------------------------------------------------------------------
# packages with different toolchains must be stored in separate buckets
# ---------------------------------------------------------------------------

# nng@linux-native and nng@win32-mingw must both survive as separate entries
# even when they have the same name and version.
def test_collect_separate_buckets_per_toolchain():
    tc_linux = MagicMock()
    tc_linux.__repr__ = lambda _: 'Toolchain(linux, native)'
    tc_linux.__str__  = lambda _: 'linux-native'
    tc_linux.__bool__ = lambda _: True
    tc_linux.platform = 'linux'

    tc_win32 = MagicMock()
    tc_win32.__repr__ = lambda _: 'Toolchain(win32, mingw)'
    tc_win32.__str__  = lambda _: 'win32-mingw'
    tc_win32.__bool__ = lambda _: True
    tc_win32.platform = 'win32'

    nng_linux = _pkg('nng', '1.6')
    nng_linux.toolchain = tc_linux

    nng_win32 = _pkg('nng', '1.6')
    nng_win32.toolchain = tc_win32

    root_linux = _pkg('curl', '8.0')
    root_linux.toolchain = tc_linux
    root_linux.dependencies = _deps(nng_linux)

    root_win32 = _pkg('protobuf', '3.0')
    root_win32.toolchain = tc_win32
    root_win32.dependencies = _deps(nng_win32)

    resolver = _make_resolver()
    packages = resolver.collect(this=root_linux, pkg_in=root_linux).packages
    packages = resolver.collect(this=root_win32, pkg_in=root_win32, packages=packages).packages

    nng_keys = [k for k in packages if 'nng' in k]
    # Both toolchain variants must be present as separate entries
    assert len(nng_keys) == 2


# ---------------------------------------------------------------------------
# walk_deps_with_parent()
# ---------------------------------------------------------------------------

# A package with no children yields nothing.
def test_walk_parent_leaf():
    leaf = _pkg('nng', '1.0')
    resolver = _make_resolver()
    pairs = list(resolver.walk_deps_with_parent(leaf))
    assert pairs == []


# A single-level dependency yields (child, parent).
def test_walk_parent_one_level():
    child = _pkg('openssl', '3.0')
    root  = _pkg('curl', '8.0')
    root.dependencies = _deps(child)

    resolver = _make_resolver()
    pairs = list(resolver.walk_deps_with_parent(root))

    assert (child, root) in pairs


# A two-level tree yields all (child, parent) edges.
def test_walk_parent_nested():
    c = _pkg('c', '1.0')
    b = _pkg('b', '1.0')
    b.dependencies = _deps(c)
    a = _pkg('a', '1.0')
    a.dependencies = _deps(b)

    resolver = _make_resolver()
    pairs = list(resolver.walk_deps_with_parent(a))

    assert (b, a) in pairs
    assert (c, b) in pairs


# With skip_build_only=True, build_only nodes are still yielded as direct
# children but their own subtrees are NOT recursed into.
def test_walk_parent_skip_build_only():
    gtest_child = _pkg('gtest_helper', '0.1')   # transitive dep inside gtest
    build_dep = _pkg('gtest', '1.0', build_only=True)
    build_dep.dependencies = _deps(gtest_child)

    runtime = _pkg('openssl', '3.0')
    root    = _pkg('mylib', '1.0')
    root.dependencies = _deps(build_dep, runtime)

    resolver = _make_resolver()
    pairs = list(resolver.walk_deps_with_parent(root, skip_build_only=True))

    children = [child for child, _ in pairs]
    assert runtime     in children   # normal dep is yielded
    assert build_dep   in children   # build_only dep is still yielded by root
    assert gtest_child not in children  # but gtest's subtree is not traversed


# ---------------------------------------------------------------------------
# walk_deps_with_count()
# ---------------------------------------------------------------------------

# Depth starts at 0 for direct children.
def test_walk_count_depth_zero():
    child = _pkg('openssl', '3.0')
    root  = _pkg('curl', '8.0')
    root.dependencies = _deps(child)

    resolver = _make_resolver()
    items = list(resolver.walk_deps_with_count(root))

    assert (child, 0) in items


# Second-level children have depth 1.
def test_walk_count_depth_nested():
    c = _pkg('c', '1.0')
    b = _pkg('b', '1.0')
    b.dependencies = _deps(c)
    a = _pkg('a', '1.0')
    a.dependencies = _deps(b)

    resolver = _make_resolver()
    items = list(resolver.walk_deps_with_count(a))

    assert (b, 0) in items
    assert (c, 1) in items


# A leaf package yields nothing.
def test_walk_count_leaf():
    leaf = _pkg('nng', '1.0')
    resolver = _make_resolver()
    assert list(resolver.walk_deps_with_count(leaf)) == []


# skip_build_only=True: build_only nodes are still yielded but their subtrees
# are not recursed into.
def test_walk_count_skip_build_only():
    gtest_child = _pkg('gtest_helper', '0.1')   # transitive dep inside gtest
    build_dep = _pkg('gtest', '1.9', build_only=True)
    build_dep.dependencies = _deps(gtest_child)

    runtime = _pkg('openssl', '3.0')
    root    = _pkg('mylib', '1.0')
    root.dependencies = _deps(build_dep, runtime)

    resolver = _make_resolver()
    items = list(resolver.walk_deps_with_count(root, skip_build_only=True))

    children = [pkg for pkg, _ in items]
    assert runtime     in children   # normal dep is yielded
    assert build_dep   in children   # build_only dep is still yielded by root
    assert gtest_child not in children  # but gtest's subtree is not traversed


# ---------------------------------------------------------------------------
# collect() — build_only flag not inherited to children (bug regression)
# ---------------------------------------------------------------------------

# Two build_only packages each pull in a different version of the same
# non-build_only child.  The conflict should be suppressed because both
# conflicting copies are only reachable through build_only parents.
# Reported bug: collect() raises RuntimeError at the conflict-check because
# the build_only flag is not propagated from parent to child, so neither
# shared_v1 nor shared_v2 appears build_only at the point of the check.
def test_collect_build_only_parent_children_conflict_suppressed():
    shared_v1 = _pkg('shared', '1.0')   # NOT build_only itself
    shared_v2 = _pkg('shared', '2.0')   # NOT build_only itself

    build_dep_a = _pkg('build_dep_a', '1.0', build_only=True)
    build_dep_a.dependencies = _deps(shared_v1)

    build_dep_b = _pkg('build_dep_b', '1.0', build_only=True)
    build_dep_b.dependencies = _deps(shared_v2)

    root = _pkg('myapp', '1.0')
    root.dependencies = _deps(build_dep_a, build_dep_b)

    resolver = _make_resolver()
    # Must not raise — both conflicting versions are only reachable through
    # build_only parents, so the version difference is irrelevant at runtime.
    result = resolver.collect(this=root, pkg_in=root)

    assert not result.conflicts
    assert repr(root) in result.packages
    assert repr(build_dep_a) in result.packages
    assert repr(build_dep_b) in result.packages


# ---------------------------------------------------------------------------
# run() — resolution model (top-level entries decide, runtime path wins)
# ---------------------------------------------------------------------------

def _run(resolver, *entries, transitive=True, skip_build_only=True):
    return resolver.run(
        {repr(p): p for p in entries},
        transitive=transitive,
        skip_build_only=skip_build_only,
    )


# a) top-level B-2.0 overrides the nested requirement A->B-1.0 (warning).
def test_run_top_level_overrides_nested_version():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('b', '1.0'))
    b2 = _pkg('b', '2.0')

    result = _run(_resolver([a], [b2]), _pkg('a', '1.0'), _pkg('b', '2.0'))

    assert not result.problems
    assert result.packages['b'] is b2
    assert len(result.warnings) == 1
    assert 'b' in result.warnings[0]


# a) The order of the top-level entries does not matter.
def test_run_top_level_overrides_nested_version_reversed():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('b', '1.0'))
    b2 = _pkg('b', '2.0')

    result = _run(_resolver([b2], [a]), _pkg('b', '2.0'), _pkg('a', '1.0'))

    assert not result.problems
    assert result.packages['b'] is b2
    assert len(result.warnings) == 1


# b) a wildcard top-level entry adopts the nested version.
def test_run_wildcard_adopts_nested_version():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('b', '1.0'))

    result = _run(_resolver([a]), _pkg('a', '1.0'), _pkg('b', ''))

    assert not result.problems
    assert not result.warnings
    assert result.packages['b'].version == '1.0'


# c) conflicting nested versions without a top-level entry for the package.
def test_run_nested_conflict_with_fixed_entries_fails():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '2.0'))

    result = _run(_resolver([a], [b]), _pkg('a', '1.0'), _pkg('b', '1.0'))

    assert len(result.problems) == 1
    assert 'Version conflict' in result.problems[0]


# c) same, with a wildcard entry whose only candidate conflicts.
def test_run_nested_conflict_with_wildcard_entry_fails():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '2.0'))

    result = _run(_resolver([a], [b]), _pkg('a', '1.0'), _pkg('b', ''))

    assert len(result.problems) == 1
    assert 'Could not resolve' in result.problems[0]


# d) a wildcard top-level entry picks the highest requested version.
def test_run_wildcard_top_level_picks_highest_nested_version():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '2.0'))

    entries = (_pkg('a', '1.0'), _pkg('b', '1.0'), _pkg('c', ''))
    result = _run(_resolver([a], [b]), *entries)

    assert not result.problems
    assert result.packages['c'].version == '2.0'
    assert len(result.warnings) == 1
    assert 'c' in result.warnings[0]


# d) the highest version is picked independent of the order of requests.
def test_run_wildcard_top_level_picks_highest_nested_version_reversed():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '2.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '1.0'))

    entries = (_pkg('a', '1.0'), _pkg('b', '1.0'), _pkg('c', ''))
    result = _run(_resolver([a], [b]), *entries)

    assert not result.problems
    assert result.packages['c'].version == '2.0'


# d) a fixed top-level entry decides; both nested requirements are overridden.
def test_run_fixed_top_level_overrides_all_nested_versions():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '2.0'))
    c3 = _pkg('c', '3.0')

    entries = (_pkg('a', '1.0'), _pkg('b', '1.0'), _pkg('c', '3.0'))
    result = _run(_resolver([a], [b], [c3]), *entries)

    assert not result.problems
    assert result.packages['c'] is c3
    assert len(result.warnings) == 2


# The nested subtree of an overridden package is not collected.
def test_run_overridden_nested_package_subtree_not_collected():
    b1 = _pkg('b', '1.0')
    b1.dependencies = _deps(_pkg('only_in_b1', '1.0'))
    a = _pkg('a', '1.0')
    a.dependencies = _deps(b1)

    result = _run(_resolver([a], [_pkg('b', '2.0')]),
                  _pkg('a', '1.0'), _pkg('b', '2.0'))

    assert 'only_in_b1' not in result.packages


# A wildcard top-level entry with constraints that no nested version
# satisfies is reported.
def test_run_wildcard_top_level_constraint_violated_by_all_nested():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    c_in = _pkg('c', '')
    c_in.version_constraints = '>=2.0'

    result = _run(_resolver([a]), _pkg('a', '1.0'), c_in)

    assert len(result.problems) == 1
    assert 'Version conflict' in result.problems[0]


# A wildcard top-level entry with a localversion adopts the nested version
# with a matching local segment.
def test_run_wildcard_localversion_adopts_matching_nested_version():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0.0.1.dev1+rbbuild.1234'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '2.0.0.1'))
    c_in = _pkg('c', '')
    c_in.localversion = 'rbbuild.1234'

    result = _run(_resolver([a], [b]), _pkg('a', '1.0'), _pkg('b', '1.0'), c_in)

    assert not result.problems
    assert result.packages['c'].version == '1.0.0.1.dev1+rbbuild.1234'


def test_run_wildcard_localversion_violated_by_all_nested():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '2.0.0.1'))
    c_in = _pkg('c', '')
    c_in.localversion = 'rbbuild.1234'

    result = _run(_resolver([a]), _pkg('a', '1.0'), c_in)

    assert len(result.problems) == 1
    assert 'Version conflict' in result.problems[0]


# 7) The version is taken from the runtime path regardless of the order of
# the entries.
def test_run_runtime_path_wins_version_regardless_of_order():
    for build_first in (True, False):
        build_a = _pkg('build_a', '1.0', build_only=True)
        build_a.dependencies = _deps(_pkg('b', '2.0'))
        runtime_x = _pkg('x', '1.0')
        runtime_x.dependencies = _deps(_pkg('b', '1.0'))

        entries = [_pkg('build_a', '1.0', build_only=True), _pkg('x', '1.0')]
        outs = [[build_a], [runtime_x]]
        if not build_first:
            entries.reverse()
            outs.reverse()

        result = _run(_resolver(*outs), *entries)

        assert not result.problems
        assert result.packages['b'].version == '1.0'
        assert result.packages['b'].build_only is False


# Two nested requirements on runtime paths still conflict when both
# paths are runtime (rule 4).
def test_run_nested_runtime_conflict_is_reported_in_both_orders():
    for swap in (False, True):
        x = _pkg('x', '1.0')
        x.dependencies = _deps(_pkg('b', '1.0'))
        y = _pkg('y', '1.0')
        y.dependencies = _deps(_pkg('b', '2.0'))
        entries = [_pkg('x', '1.0'), _pkg('y', '1.0')]
        outs = [[x], [y]]
        if swap:
            entries.reverse()
            outs.reverse()

        result = _run(_resolver(*outs), *entries)

        assert len(result.problems) == 1


# 2) Children of a top-level build_only package are build_only for
# consumers, too.
def test_run_children_of_top_level_build_only_are_build_only():
    a = _pkg('a', '1.0', build_only=True)
    a.dependencies = _deps(_pkg('b', '1.0'))

    result = _run(_resolver([a]), _pkg('a', '1.0', build_only=True))

    assert result.packages['a'].build_only is True
    assert result.packages['b'].build_only is True


# The packages of the repository are not modified by the flag propagation.
def test_run_flag_propagation_does_not_modify_input_packages():
    b = _pkg('b', '1.0')
    a = _pkg('a', '1.0', build_only=True)
    a.dependencies = _deps(b)

    _run(_resolver([a]), _pkg('a', '1.0', build_only=True))

    assert b.build_only is False


# 7) A runtime path to a package that is also a top-level build_only entry
# makes it a runtime package for consumers.
def test_run_runtime_path_to_top_level_build_only_entry():
    x = _pkg('x', '1.0')
    x.dependencies = _deps(_pkg('a', '1.0'))
    a = _pkg('a', '1.0', build_only=True)

    result = _run(_resolver([x], [a]),
                  _pkg('x', '1.0'), _pkg('a', '1.0', build_only=True))

    assert not result.problems
    assert result.packages['a'].build_only is False


# 6) A top-level traverse=False package is returned without its
# dependencies, and is build_only for consumers.
def test_run_top_level_traverse_false_cuts_subtree():
    b = _pkg('b', '1.0')
    a = _pkg('a', '1.0', traverse=False)
    a.dependencies = _deps(b)

    result = _run(_resolver([a]), _pkg('a', '1.0', traverse=False))

    assert 'b' not in result.packages
    assert result.packages['a'].dependencies == {}
    assert result.packages['a'].build_only is True
    # the repository object keeps its dependencies
    assert a.dependencies == _deps(b)


# traverse=False on a top-level package also holds for the non-transitive
# result (used by promote).
def test_run_top_level_traverse_false_non_transitive():
    a = _pkg('a', '1.0', traverse=False)
    a.dependencies = _deps(_pkg('b', '1.0'))

    result = _run(_resolver([a]), _pkg('a', '1.0', traverse=False),
                  transitive=False)

    assert result.packages['a'].dependencies == {}


# Top-level entries are reported to the caller (needed by install).
def test_run_reports_top_level_ids():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('b', '1.0'))

    result = _run(_resolver([a]), _pkg('a', '1.0'))

    assert set(result.top_level) == {'a'}
    assert 'b' in result.packages


# A wildcard requested by the subtree of another wildcard is resolved, too.
def test_run_wildcard_chain_adopts_nested_versions():
    w1 = _pkg('w1', '1.0')
    w1.dependencies = _deps(_pkg('w2', '3.0'))
    a = _pkg('a', '1.0')
    a.dependencies = _deps(w1)

    entries = (_pkg('a', '1.0'), _pkg('w1', ''), _pkg('w2', ''))
    result = _run(_resolver([a]), *entries)

    assert not result.problems
    assert result.packages['w1'].version == '1.0'
    assert result.packages['w2'].version == '3.0'


# The highest requested version that satisfies the constraints is adopted.
def test_run_wildcard_adopts_highest_nested_version_within_constraints():
    a = _pkg('a', '1.0')
    a.dependencies = _deps(_pkg('c', '1.0'))
    b = _pkg('b', '1.0')
    b.dependencies = _deps(_pkg('c', '3.0'))
    c_in = _pkg('c', '')
    c_in.version_constraints = '<2.0'

    result = _run(_resolver([a], [b]), _pkg('a', '1.0'), _pkg('b', '1.0'), c_in)

    assert not result.problems
    assert result.packages['c'].version == '1.0'


# A wildcard candidate that differs from a top-level package in its subtree
# is accepted with a warning (top-level entries decide).
def test_run_wildcard_candidate_overridden_by_top_level_warns():
    c3 = _pkg('c', '3.0')
    candidate = _pkg('w', '1.0')
    candidate.dependencies = _deps(_pkg('c', '1.0'))

    result = _run(_resolver([c3], [candidate]), _pkg('c', '3.0'), _pkg('w', ''))

    assert not result.problems
    assert result.packages['c'] is c3
    assert result.packages['w'] is candidate
    assert len(result.warnings) == 1


# --- warning deduplication ---

# a shared nested package (diamond) overridden by a top-level entry; the
# search results are the packages returned for the entries a and c
def _overridden_diamond():
    left = _pkg('left', '1.0')
    left.dependencies = _deps(_pkg('c', '1.0'))
    right = _pkg('right', '1.0')
    right.dependencies = _deps(_pkg('c', '1.0'))
    a = _pkg('a', '1.0')
    a.dependencies = _deps(left, right)
    return [a], [_pkg('c', '3.0')]


def _diamond_entries():
    return _pkg('a', '1.0'), _pkg('c', '3.0')


# The same warning is reported once per run, although the shared package is
# visited on two paths.
def test_run_warning_is_unique_within_run():
    result = _run(_resolver(*_overridden_diamond()), *_diamond_entries())

    assert len(result.warnings) == 1


def test_run_warning_is_not_unique_within_run_when_verbose():
    resolver = _make_resolver(_overridden_diamond(), verbose=True)

    result = _run(resolver, *_diamond_entries())

    assert len(result.warnings) == 2


# Repeated runs (fetch, install, package) print a warning only once, but
# every result still contains it.
def test_run_warning_is_printed_once_across_runs():
    resolver = _resolver(*_overridden_diamond(), *_overridden_diamond())

    with patch('rbbuild.resolver.resolver.term') as mock_term:
        first = _run(resolver, *_diamond_entries())
        second = _run(resolver, *_diamond_entries())

    assert len(first.warnings) == 1
    assert len(second.warnings) == 1
    assert mock_term.warning.call_count == 1


def test_run_warning_is_printed_every_time_when_verbose():
    resolver = _make_resolver(
        [*_overridden_diamond(), *_overridden_diamond()], verbose=True)

    with patch('rbbuild.resolver.resolver.term') as mock_term:
        _run(resolver, *_diamond_entries())
        _run(resolver, *_diamond_entries())

    # two copies of the warning per run
    assert mock_term.warning.call_count == 4


# A toolchain-less dependency from a channel is traversed for any toolchain.
def test_collect_traverses_child_without_toolchain_from_channel():
    tc_linux = MagicMock()
    tc_linux.__repr__ = lambda _: 'linux-native'
    tc_linux.platform = 'linux'

    child = _pkg('pure_data', '1.0')
    child.channel = MagicMock()

    root = _pkg('mylib', '1.0')
    root.toolchain = tc_linux
    root.dependencies = _deps(child)

    result = _make_resolver().collect(this=root, pkg_in=root)

    assert repr(child) in result.packages


# A toolchain-less dependency without channel (e.g., PyPI) is not traversed.
def test_collect_skips_child_without_toolchain_and_channel():
    tc_linux = MagicMock()
    tc_linux.__repr__ = lambda _: 'linux-native'
    tc_linux.platform = 'linux'

    child = _pkg('some_pypi_pkg', '1.0')

    root = _pkg('mylib', '1.0')
    root.toolchain = tc_linux
    root.dependencies = _deps(child)

    result = _make_resolver().collect(this=root, pkg_in=root)

    assert repr(child) not in result.packages
