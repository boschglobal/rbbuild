# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import inspect
import json
import re

from copy import copy
from pathlib import Path
from packaging.version import Version, InvalidVersion
from typing import Callable, Iterator, Optional

from rbbuild.core.channel import Channel
from rbbuild.core.toolchain import Toolchain
from rbbuild.deps.parser import DepsParser
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.package import Package

from rbbuild.service.remote_service import AuthMethod, truststore_from_config
from rbbuild.service.utility import matches_localversion, version_sort_function

from .repository import Repository


# RepositoryManager is the central class for dispatching package operations to
# a Repository service (e.g., Artifactory).
#
# In the following, the relation between RepositoryManager, the Repository method
# and cache behavior is described (implemented by LocalFileStorage).
#
# +=+====================+=====================================+===========================+
# |#| Use Case           | Methods                             | Cache behavior            |
# +=+====================+=====================================+===========================+
# |1| Search versions    | repoman.search()                    | cache.get_versions()      |
# | | pkq                |   service.list_versions()           | cache.get_package()       |
# | | rbbuild -F         |   service.find_package()            | cache.add(manifest)       |
# +-+--------------------+-------------------------------------+---------------------------+
# |2| Download package   | repoman.download()                  | cache.get(file)           |
# | | rbbuild -F         |   service.download()                | cache.add(file)           |
# +-+--------------------+-------------------------------------+---------------------------+
# |3| Upload package     | repoman.upload()                    | (none)                    |
# | | rbbuild --publish  |   service.upload_component()        |                           |
# +-+--------------------+-------------------------------------+---------------------------+
# |4| Delete package     | repoman.delete()                    | cache.delete()            |
# | | rbbuild --delete   |   service.delete()                  |                           |
# +-+--------------------+-------------------------------------+---------------------------+
# |5| List package names | repoman.list_package_names()        |                           |
# | | pkq -l             |   service.list_package_names()      |                           |
# +=+====================+=====================================+===========================+

class RepositoryManager:
    def __init__(
        self,
        deps_parser: DepsParser,
        selected_channel: Channel,
        target_toolchain: Toolchain,
        op_mode: OperationMode,
        cache_provider,
        services_config: dict,
        user_config: dict,           # user overrides and credentials
        toolchains_config: dict,
        **providers
    ):
        self.deps_parser = deps_parser
        self.selected_channel = selected_channel
        self.target_toolchain = target_toolchain
        self.op_mode = op_mode
        self._cache_provider = cache_provider
        self._providers = providers
        self._services_config = services_config
        self._user_config = user_config if user_config else {}
        self._toolchains_config = toolchains_config if toolchains_config else {}


    # Generic service retrieval by registered identifier and channel
    def service(self, channel: Channel) -> Repository:
        if not channel:
            channel = self.selected_channel
        config = self._services_config.get(channel.remote_service, {})
        user = self._user_config.get(channel.remote_service, {})
        if not config:
            raise LookupError(f'Service {channel!s} is not configured for the current profile!')

        service_type = config['type']
        provider = self._providers.get(service_type)
        if not provider:
            raise LookupError(
                f'Service type "{service_type}" of {channel!s} is not available. '
                f'Install the package that provides it.'
            )

        kwargs = dict(
            channel = channel,
            url = config.get('url'),
            auth_method = AuthMethod.from_config(config, channel.remote_service),
            user = user.get('user'),
            credentials = user.get('credentials'),
            truststore = truststore_from_config(config, channel.remote_service),
            cache = self._cache_provider(
                channel = channel,
            ),
        )

        # Types only get 'options' (profile settings of the service) and
        # 'user_options' (user config entries) if they declare them, so that
        # plugins written without them keep working.
        cls = getattr(provider, 'cls', None)
        parameters = inspect.signature(cls).parameters if isinstance(cls, type) else {}
        if 'options' in parameters:
            kwargs['options'] = config
        if 'user_options' in parameters:
            kwargs['user_options'] = user

        return provider(**kwargs)


    #  This method searches for packages specified by Package constraints
    #  (name, version, channel, toolchain, etc)
    #  The returned iterator is sorted from newest to oldest version
    #  Package objects will be created from manifest.json and returned
    def search(
        self,
        *,
        pkg: Package = None,
        deps_item: str = None,     # alternate mode, parse deps item to create pkg
        channel: Channel = None,   # determine service. Order: channel, pkg.channel, default
    ) -> Iterator[Package]:
        pkg = self._resolve_pkg(pkg, deps_item)
        channel = self._resolve_channel(pkg, channel)
        yield from self._search(pkg, channel, light=False)


    # Like search(), but skips downloading/parsing the manifest entirely
    def search_versions(
        self,
        *,
        pkg: Package = None,
        deps_item: str = None,
        channel: Channel = None,
    ) -> Iterator[Package]:
        pkg = self._resolve_pkg(pkg, deps_item)
        channel = self._resolve_channel(pkg, channel)
        yield from self._search(pkg, channel, light=True)


    # Like search(), but for a pinned name+version whose toolchain is not
    # known/constrained: instead of guessing a single toolchain, this tries
    # every toolchain configured in the current profile.
    # Used for display/inspection (e.g., pkq -l <name>-<version>).
    def search_toolchains(
        self,
        *,
        pkg: Package = None,
        deps_item: str = None,
        channel: Channel = None,
    ) -> Iterator[Package]:
        pkg = self._resolve_pkg(pkg, deps_item)
        channel = self._resolve_channel(pkg, channel)

        if pkg.toolchain:
            yield from self.search(pkg=pkg, channel=channel)
            return

        seen = set()
        for tcid in sorted(self._toolchains_config):
            tc_pkg = copy(pkg)
            tc_pkg.toolchain = self.deps_parser.toolchain_factory(tcid=tcid)
            for found in self.search(pkg=tc_pkg, channel=channel):
                # A package without toolchain is found for every toolchain
                key = (found.version, str(found.toolchain))
                if key in seen:
                    continue
                seen.add(key)
                yield found


    def _resolve_pkg(self, pkg: Package, deps_item: str) -> Package:
        if not pkg:
            pkg = self.deps_parser.parse_item(deps_item)

            if not pkg:
                raise LookupError(f'Could not find package {deps_item!s}')

        return pkg


    def _resolve_channel(self, pkg: Package, channel: Channel) -> Channel:
        if not channel:
            channel = pkg.channel

        if not channel:
            channel = self.selected_channel

        return channel


    # Shared by search() and search_versions(). Order is important here: in
    # some cases, a package with the same version exists in the current
    # channel as well as the redirected channel. By returning the current
    # channel result first, we ensure consistencies are preserved.
    def _search(
        self,
        pkg: Package,
        channel: Channel,
        light: bool,
    ) -> Iterator[Package]:
        if not channel.redirect_repos:
            yield from self._search_in_channel(pkg, channel, light=light)

        # Unfortunately, we need to re-sort in case we are using redirect_repos.
        # This might result in slower performance for very large repositories.
        else:
            packages = list(self._search_in_channel(pkg, channel, light=light))

            for chname in channel.redirect_repos:
                # A pinned version is unique: stop at the first channel with a hit
                if pkg.version and packages:
                    break
                ch = self.deps_parser.channel_factory(name=chname)
                if ch:
                    packages.extend(list(self._search_in_channel(pkg, ch, light=light)))

            yield from sorted(packages, key=lambda pkg: version_sort_function(pkg.version), reverse=True)


    def _search_in_channel(
        self,
        pkg: Package,
        channel: Channel,
        light: bool,
    ) -> Iterator[Package]:
        service = self.service(channel)

        for version in service.list_versions(pkg.name, pkg.version):
            # check constraints
            if pkg.version_constraints:
                try:
                    pyversion = Version(version)
                    if pyversion not in pkg.version_constraints:
                        continue
                except InvalidVersion:
                    # Try to match legacy rbbuild version strings
                    if re.match(r'\d+\.\d+\.\d+-.+\.\d+', version):
                        ver_stripped = re.sub(r'(\d+\.\d+\.\d+)-.+\.(\d+)', r'\1.\2', version)
                        try:
                            pyversion = Version(ver_stripped)
                            if pyversion not in pkg.version_constraints:
                                continue
                        except InvalidVersion:
                            pass
                        except Exception:
                            raise
                except Exception:
                    raise

            if pkg.localversion and not matches_localversion(version, pkg.localversion):
                continue

            toolchain = pkg.toolchain

            if light:
                # Requested by caller to skip importing manifest data
                pkg_out = Package(name=pkg.name, version=version)
            else:
                if not toolchain and service.channel.type == 'rbbuild':
                    toolchain = self.target_toolchain

                qpkg = copy(pkg)
                qpkg.version = version
                qpkg.toolchain = toolchain

                pkg_out = service.find_package(qpkg)

                # A package without toolchain is compatible with every toolchain
                if not pkg_out and toolchain and service.channel.type == 'rbbuild':
                    toolchain = None
                    qpkg.toolchain = None
                    pkg_out = service.find_package(qpkg)

                if not pkg_out:
                    continue

                # TODO: this works fine, but seems unnecessarily complicated
                if service.channel.type == 'rbbuild':
                    pkg_out.component_specifier = pkg.component_specifier
                    if pkg_out.component_specifier and pkg_out.component_specifier.items:
                        components_filtered = []
                        for comp in pkg_out.components:
                            if pkg_out.component_specifier.check(comp.name, comp.suffix, None):
                                spec = pkg_out.component_specifier
                                if spec.check(comp.name, comp.suffix, 'build_only') is True:
                                    comp.build_only = True
                                if spec.check(comp.name, comp.suffix, 'traverse') is False:
                                    comp.traverse = False
                                components_filtered.append(comp)
                        pkg_out.components = components_filtered

            # Map input pkg parameters to the output
            pkg_out.channel = service.channel
            pkg_out.toolchain = toolchain

            pkg_out.installdir = pkg.installdir
            pkg_out.install_action = pkg.install_action

            yield pkg_out


    def list_package_names(self, channel: Channel=None) -> Iterator[str]:
        service = self.service(channel)
        for pkgname in service.list_package_names(pattern=None):
            yield pkgname


    # Return toolchain strings for all toolchains available for an exact name+version.
    def list_toolchains(self, name: str, version: str, channel: Channel=None) -> Iterator[str]:
        service = self.service(channel)
        prefix = f'{name}-{version}-'
        suffix = '-manifest.json'

        cached_fnames = set(service.cache.list_manifest_names(name, version))
        remote_fnames = set(service.list_manifest_names(name, version))

        results = {}  # canonical → (fname, tc_or_None)
        for fname in cached_fnames | remote_fnames:
            if not (fname.startswith(prefix) and fname.endswith(suffix)):
                continue
            tc_str = fname[len(prefix):-len(suffix)]
            if not tc_str:
                continue
            try:
                tc = self.deps_parser.toolchain_factory(tcid=tc_str)
                canonical = str(tc)
            except LookupError:
                tc = None
                canonical = tc_str  # not in profile; list it but can't cache
            if canonical not in results:
                results[canonical] = (fname, tc)

        for canonical in sorted(results):
            fname, tc = results[canonical]
            # Cache the manifest as a side-effect of find_package (same as rbbuild -F)
            if tc and fname in remote_fnames - cached_fnames:
                cache_pkg = Package(name=name, version=version)
                cache_pkg.toolchain = tc
                service.find_package(cache_pkg)
            yield canonical


    def download(
        self,
        pkg: Package,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> Iterator[Component]:
        service = self.service(pkg.channel)
        if progress_cb:
            service.progress_cb = progress_cb
        for component in service.find_components(pkg=pkg):
            yield component


    def upload(self, pkg: Package) -> Iterator[Component]:
        if pkg.channel.publish is False and self.op_mode.force is not True:
            term.info(f'[{term.yellow("skipped")}]', 'Upload is disabled in profile configuration')
            return
        service = self.service(pkg.channel)
        all_components = [*pkg.components]
        if pkg.manifest:
            all_components.append(pkg.manifest)
        for component in all_components:
            service.upload_component(
                name=pkg.name,
                version=pkg.version,
                component=component,
            )
            yield component


    def delete(self, pkg: Package):
        if pkg.channel.permissions != 'delete':
            raise PermissionError(f'No permission to delete from {term.bright_white(pkg.channel.name)}: maximum permission level is set to {term.red(pkg.channel.permissions)}')

        service = self.service(pkg.channel)
        service.delete(name=pkg.name, version=pkg.version)


    # Copy pkg from pkg.channel to destination_channel.
    # Yields each Component when it was copied/uploaded, or None when it was
    # skipped (e.g., already existed).
    def promote(
        self,
        pkg: Package,
        destination_channel: Channel,
    ) -> Iterator[Optional[Component]]:
        src_service = self.service(pkg.channel)
        dst_service = self.service(destination_channel)

        # Use server-side copy when both ends share the same service type and
        # the same base URL (i.e. same Artifactory instance).
        can_copy = (
            type(src_service) is type(dst_service)
            and hasattr(src_service, 'copy')
            and src_service.url == dst_service.url
        )

        # --- data components ---
        for comp in pkg.components:
            if can_copy:
                copied = src_service.copy(
                    localfile=Path(comp.filename),
                    name=pkg.name,
                    version=pkg.version,
                    source_channel=pkg.channel,
                    destination_channel=destination_channel,
                    sha1sum=comp.checksum,
                )
            else:
                # Cross-server: download each component then upload to destination
                local_comp = None
                for c in self.download(pkg):
                    if c.filename == comp.filename:
                        local_comp = c
                        break
                if local_comp:
                    dst_service.upload_component(
                        name=pkg.name,
                        version=pkg.version,
                        component=local_comp,
                    )
                    copied = True
                else:
                    copied = False

            yield comp if copied else None

        # --- manifest: regenerate for the destination channel and upload ---
        pkg_dst = copy(pkg)
        pkg_dst.channel = destination_channel
        pkg_dst.url = dst_service.resource_url(pkg_dst)
        manifest_data = dst_service.manifest.from_package(pkg_dst)
        manifest_filename = dst_service.manifest.make_filename(
            name=pkg_dst.name,
            version=pkg_dst.version,
            toolchain=pkg_dst.toolchain,
        )
        manifest_tmp = dst_service.tmpdir / manifest_filename
        try:
            with open(manifest_tmp, 'w') as fd:
                json.dump(manifest_data, fd, indent=4)
            manifest_comp = Component(
                name='manifest',
                suffix='json',
                filename=manifest_filename,
                localpath=manifest_tmp,
            )
            dst_service.upload_component(
                name=pkg_dst.name,
                version=pkg_dst.version,
                component=manifest_comp,
            )
            yield manifest_comp
        finally:
            manifest_tmp.unlink(missing_ok=True)

