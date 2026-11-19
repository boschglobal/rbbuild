# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from copy import copy
from dataclasses import replace
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple

from rbbuild.package.package import Package
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.librbb.term import term
from rbbuild.service.repository.manager import RepositoryManager
from rbbuild.service.utility import matches_localversion, version_sort_function


# Result of collect(): collected packages, conflicts (if any) and warnings
class CollectResult(NamedTuple):
    packages: Dict[str, Package]
    conflicts: Dict[str, str]
    warnings: Sequence[str] = ()


# Result of run(): resolved packages, resolution problems (if any), warnings
# and the ids of the top-level packages in `packages`
class ResolveResult(NamedTuple):
    packages: Dict[str, Package]
    problems: List[str]
    warnings: Sequence[str] = ()
    top_level: Sequence[str] = ()


class Resolver:
    def __init__(
        self,
        repoman: RepositoryManager,
        op_mode: OperationMode,
    ):
        self.repoman = repoman
        self.op_mode = op_mode
        # Warnings already printed by run(); the resolver is a singleton, so
        # fetch, install and package print each warning only once.
        self._reported: Set[str] = set()


    @property
    def _verbose(self) -> bool:
        return self.op_mode.verbose


    def _warn(self, warnings: List[str], message: str):
        if self._verbose or message not in warnings:
            warnings.append(message)


    @staticmethod
    def _version_allowed(pkg_in: Package, version: str) -> bool:
        if pkg_in.version_constraints and version not in pkg_in.version_constraints:
            return False
        if pkg_in.localversion:
            return matches_localversion(version, pkg_in.localversion)
        return True


    # transitive: if set to True, transitive dependencies will also be returned
    # skip_build_only: skip dependencies that are build_only or have traverse=False if True
    def run(
        self,
        packages_in: Dict[str, Package],
        transitive: bool,
        skip_build_only: bool=False,
    ) -> ResolveResult:
        packages = {}              # top-level packages
        all_packages = {}          # all packages; will be returned if transitive is True
        wildcard_packages = {}     # non-fixed versions
        problems: List[str] = []   # list of version-conflict messages
        warnings: List[str] = []
        top_ids: Set[str] = set()  # ids of top-level packages in all_packages
        handled: Set[str] = set()  # wildcards resolved from nested requests
        resolved_fixed: List[Tuple[Package, Package]] = []

        # First pass: separate fixed and wildcard versions
        for pkg_in in packages_in.values():
            if pkg_in.version:
                pkg = None
                for pkg in self.repoman.search(pkg=pkg_in):
                    break
                if not pkg:
                    err_msg = f'Could not resolve {pkg_in}'
                    if pkg_in.toolchain:
                        err_msg += f' ({pkg_in.toolchain})'
                    problems.append(err_msg)
                    continue

                resolved_fixed.append((pkg_in, pkg))
            else:
                wildcard_packages[repr(pkg_in)] = pkg_in

        # Fixed top-level packages are registered before any subtree is
        # collected, so that they override nested requirements.
        for _, pkg in resolved_fixed:
            pkgid = self._pkgid(pkg, pkg)
            all_packages[pkgid] = self._effective(pkg, self._is_runtime(pkg))
            top_ids.add(pkgid)

        # Requests of nested packages for wildcard top-level packages
        requests: Dict[str, Dict[str, Package]] = {
            key: {} for key in wildcard_packages
        }

        for pkg_in, pkg in resolved_fixed:
            result = self.collect(
                this=pkg,
                pkg_in=pkg,
                packages=all_packages,
                skip_build_only=skip_build_only,
                top_level=top_ids,
                wildcards=requests,
                warnings=warnings,
            )
            all_packages = result.packages
            problems.extend(result.conflicts.values())
            packages[repr(pkg_in)] = all_packages[self._pkgid(pkg, pkg)]

        # Second pass: wildcards requested by nested packages adopt the
        # highest requested version. Collecting the subtree of the adopted
        # package can request further wildcards.
        progress = True
        while progress:
            progress = False
            for key, pkg_in in wildcard_packages.items():
                if not requests.get(key):
                    continue

                progress = True
                handled.add(key)
                candidates = requests.pop(key)
                versions = sorted(candidates, key=version_sort_function, reverse=True)
                versions_ok = [v for v in versions if self._version_allowed(pkg_in, v)]
                if not versions_ok:
                    problems.append(self._version_conflict_message(
                        pkg_in, candidates[versions[0]]))
                    continue

                winner = candidates[versions_ok[0]]
                if len(versions) > 1:
                    self._warn(
                        warnings,
                        f'Different versions of {pkg_in.name} are requested '
                        f'({", ".join(versions)}); using {winner.version}')

                pkgid = self._pkgid(winner, winner)
                top_ids.add(pkgid)
                result = self.collect(
                    this=winner,
                    pkg_in=winner,
                    packages=all_packages,
                    skip_build_only=skip_build_only,
                    top_level=top_ids,
                    wildcards=requests,
                    warnings=warnings,
                )
                all_packages = result.packages
                problems.extend(result.conflicts.values())
                packages[key] = all_packages[pkgid]

        # Third pass: resolve the remaining wildcard versions
        for key, pkg_in in wildcard_packages.items():
            if key in handled:
                continue

            if key in all_packages:
                pkg = all_packages[key]
                if not self._version_allowed(pkg_in, pkg.version):
                    problems.append(self._version_conflict_message(pkg_in, pkg))
                    continue
                packages[key] = pkg
                continue

            # Before adding a wildcard, ensure that there is no conflict with
            # already added non-wildcard packages
            pkg = None
            for pkg_it in self.repoman.search(pkg=pkg_in):
                result = self.collect(
                    this=pkg_it,
                    pkg_in=pkg_it,
                    packages=None,
                    skip_build_only=skip_build_only,
                )
                # A conflict within the candidate's own subtree (unrelated to
                # all_packages) rules out this candidate just like a conflict
                # against all_packages does below - try the next one.
                if result.conflicts:
                    continue
                pkg_deps = result.packages

                # Conflict check with current package
                conflict = False
                candidate_warnings = []
                for cid, child in pkg_deps.items():
                    if cid in all_packages and child.version != all_packages[cid].version:
                        existing = all_packages[cid]
                        if cid in top_ids:
                            self._warn(
                                candidate_warnings,
                                self._override_message(existing, child))
                            continue
                        if self._is_runtime(child) and self._is_runtime(existing):
                            conflict = True
                            break

                if conflict is False:
                    pkgid = self._pkgid(pkg_it, pkg_it)
                    top_ids.add(pkgid)
                    self._merge_candidate(all_packages, pkg_deps, top_ids)
                    for message in candidate_warnings:
                        self._warn(warnings, message)
                    pkg = pkg_it
                    packages[key] = all_packages[pkgid]
                    break

            # Final check
            if not pkg:
                err_msg = f'Could not resolve {pkg_in}'
                if pkg_in.toolchain:
                    err_msg += f' ({pkg_in.toolchain})'
                problems.append(err_msg)


        for warning in warnings:
            if self._verbose or warning not in self._reported:
                term.warning(warning)
            self._reported.add(warning)

        result_packages = all_packages if transitive is True else packages
        return ResolveResult(
            packages=result_packages,
            problems=problems,
            warnings=warnings,
            top_level=tuple(top_ids),
        )


    @staticmethod
    def _pkgid(this: Package, pkg_in: Package) -> str:
        pkgid = repr(this)
        # If toolchain was not specified in the original input, we strip it away
        if '@' in pkgid and not pkg_in.toolchain:
            pkgid, _ = pkgid.split('@', maxsplit=1)
        return pkgid


    @staticmethod
    def _is_runtime(pkg: Package) -> bool:
        return not (pkg.build_only or not pkg.traverse)


    # Packages reachable only via build-only paths are returned with all
    # components marked build_only; traverse=False cuts the subtree.
    @staticmethod
    def _effective(pkg: Package, runtime: bool) -> Package:
        if runtime or (pkg.build_only and pkg.traverse):
            return pkg

        flagged = copy(pkg)
        flagged.components = [replace(c, build_only=True) for c in pkg.components]
        if not pkg.traverse:
            flagged.dependencies = {}
        return flagged


    # A top-level package keeps its own settings, but a runtime path to it
    # clears build_only on the components that the runtime path needs.
    @staticmethod
    def _merge_runtime(top: Package, nested: Package) -> Package:
        needed = {(c.name, c.suffix): c.build_only for c in nested.components}
        merged = copy(top)
        merged.components = [
            replace(c, build_only=c.build_only and needed.get((c.name, c.suffix), True))
            for c in top.components
        ]
        return merged


    def _merge_candidate(
        self,
        all_packages: Dict[str, Package],
        candidate_packages: Dict[str, Package],
        top_ids: Set[str],
    ):
        for cid, child in candidate_packages.items():
            existing = all_packages.get(cid)
            if existing is None:
                all_packages[cid] = child
            elif cid in top_ids:
                continue
            elif self._is_runtime(child) and not self._is_runtime(existing):
                all_packages[cid] = child


    def _override_message(self, top: Package, nested: Package) -> str:
        return f'Using top-level {top} instead of the requested {nested}'


    # Recursive depth-first search implementation shared by collect().
    # Mutates `packages` in place and yields (package, conflict_message)
    # for every visited node.
    def _collect_iter(
        self,
        this: Package,
        pkg_in: Package,
        packages: Dict[str, Package],
        skip_build_only: bool=False,
        build_only_inherited: bool=False,
        top_level: Optional[Set[str]]=None,
        wildcards: Optional[Dict[str, Dict[str, Package]]]=None,
        warnings: Optional[List[str]]=None,
    ) -> Iterator[Tuple[Package, Optional[str]]]:
        # If the package has no installdir, inherit it from the resolution context.
        # This ensures transitive deps of a namespaced entry (e.g. /x64) are placed
        # in the same sub-directory as their parent.
        if not this.installdir and pkg_in.installdir:
            this = copy(this)
            this.installdir = pkg_in.installdir

        pkgid = self._pkgid(this, pkg_in)

        # build_only is inherited: a child of a build_only package is
        # treated as build_only for conflict purposes
        runtime = self._is_runtime(this) and not build_only_inherited

        conflict_message = None
        descend = True
        other = packages.get(pkgid)

        if other is None:
            key = self._wildcard_key(pkgid, wildcards)
            if key is not None:
                # Wildcard top-level package: run() adopts a requested version
                wildcards[key].setdefault(this.version, this)
                yield this, None
                return

            packages[pkgid] = self._effective(this, runtime)
        else:
            is_top = top_level is not None and pkgid in top_level
            other_runtime = self._is_runtime(other)

            if this.version != other.version:
                if is_top:
                    if warnings is not None:
                        self._warn(warnings, self._override_message(other, this))
                    descend = False
                elif runtime and not other_runtime:
                    packages[pkgid] = this
                elif runtime:
                    conflict_message = self._version_conflict_message(other, this)
            elif runtime and not other_runtime:
                packages[pkgid] = self._merge_runtime(other, this) if is_top else this

        yield this, conflict_message

        # A package with traverse=False is collected but its child dependencies are not
        if not descend or not this.traverse:
            return

        # Traverse dependencies
        for child in this.dependencies.values():
            if this.toolchain:
                # Packages without toolchain are compatible with every toolchain,
                # but only those from a channel (not, e.g., PyPI packages)
                if child.toolchain:
                    if this.toolchain.platform != child.toolchain.platform:
                        continue
                elif not child.channel:
                    continue

            if skip_build_only is True:
                if child.build_only or not child.traverse:
                    continue

            yield from self._collect_iter(
                this=child,
                pkg_in=pkg_in,
                packages=packages,
                skip_build_only=skip_build_only,
                build_only_inherited=this.build_only or build_only_inherited,
                top_level=top_level,
                wildcards=wildcards,
                warnings=warnings,
            )


    @staticmethod
    def _wildcard_key(
        pkgid: str,
        wildcards: Optional[Dict[str, Dict[str, Package]]],
    ) -> Optional[str]:
        if not wildcards:
            return None
        if pkgid in wildcards:
            return pkgid
        stripped = pkgid.split('@', maxsplit=1)[0]
        return stripped if stripped in wildcards else None


    # Recursive depth-first search: returns a CollectResult with a packages
    # dict containing all unique packages, and a conflicts dict for any
    # version conflicts encountered (empty on full success).
    #
    # `conflicts`, like `packages`, can be passed in to accumulate results
    # from multiple collect() calls into the same dict.
    #
    # top_level: ids of top-level packages; nested requirements for other
    #            versions of them are dropped with a warning.
    # wildcards: requested versions by id; nested requirements for these
    #            ids are recorded instead of collected (see run()).
    def collect(
        self,
        this: Package,
        pkg_in: Package,
        packages: Dict[str, Package]=None,
        skip_build_only: bool=False,
        build_only_inherited: bool=False,
        conflicts: Dict[str, str]=None,
        top_level: Optional[Set[str]]=None,
        wildcards: Optional[Dict[str, Dict[str, Package]]]=None,
        warnings: Optional[List[str]]=None,
    ) -> CollectResult:
        if packages is None:
            packages = {}
        if conflicts is None:
            conflicts = {}
        if warnings is None:
            warnings = []

        for pkg, conflict_message in self._collect_iter(
            this=this,
            pkg_in=pkg_in,
            packages=packages,
            skip_build_only=skip_build_only,
            build_only_inherited=build_only_inherited,
            top_level=top_level,
            wildcards=wildcards,
            warnings=warnings,
        ):
            if conflict_message:
                conflicts[repr(pkg)] = conflict_message

        return CollectResult(packages=packages, conflicts=conflicts, warnings=warnings)


    def _remove_recursive(self, pkg: Package, packages: Dict[str, Package]) -> Dict[str, Package]:
        if repr(pkg) in packages:
            del packages[repr(pkg)]

        for child in pkg.dependencies.values():
            packages = self._remove_recursive(child, packages)

        return packages


    # returns child, parent pair (used to generate PlantUML graphs in pandoc)
    def walk_deps_with_parent(self, pkg: Package, skip_build_only: bool=False) -> Iterator[Tuple[Package, Package]]:
        if skip_build_only is True:
            if pkg.build_only or not pkg.traverse:
                return

        for child in pkg.dependencies.values():
            yield child, pkg
            yield from self.walk_deps_with_parent(child, skip_build_only)


    # returns child, depth count
    def walk_deps_with_count(
        self,
        pkg: Package,
        depth=0,
        skip_build_only: bool=False,
    ) -> Iterator[Tuple[Package, int]]:
        if skip_build_only is True:
            if pkg.build_only or not pkg.traverse:
                return

        for child in pkg.dependencies.values():
            yield child, depth
            yield from self.walk_deps_with_count(
                pkg=child,
                depth=depth+1,
                skip_build_only=skip_build_only,
            )


    def _version_conflict_message(self, pkg_a: Package, pkg_b: Package):
        return ( 'Version conflict detected:\n'
                f'    {term.bright_white(str(pkg_a)):<50} {"(requested version from deps.json)"}\n'
                f'    {term.bright_white(str(pkg_b)):<50} {"(already resolved package)"}' )

