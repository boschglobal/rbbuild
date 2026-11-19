# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json
import shutil

from abc import ABCMeta, abstractmethod
from copy import copy
from pathlib import Path
from typing import Callable, Iterator, List, Tuple

from rbbuild.core.channel import Channel
from rbbuild.core.toolchain import Toolchain
from rbbuild.librbb.crypto import compute_sha1sum
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.remote_service import RemoteService, AuthMethod
from rbbuild.service.utility import version_sort_function


class LocalFileStorage:
    pass


# Raised when a package version was already published to a channel and
# cannot be overwritten (e.g. HTTP 403/409, or a pre-existing component).
class VersionConflictError(RuntimeError):
    pass


# abstract class implemented by repository instances (Artifactory, ...)
class Repository(RemoteService, metaclass=ABCMeta):
    def __init__(
        self,
        cache: LocalFileStorage,
        channel: Channel,
        manifest: Manifest,
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        RemoteService.__init__(
            self,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.cache=cache
        self.channel=channel
        self.manifest=manifest

        # Callback to print progress (terminal or UI)
        self.progress_cb: Callable[[int, int], None] = term.print_download_progress


    # Returns a list of version strings
    @abstractmethod
    def get_versions(self, name: str) -> List[str]:
        pass


    # Download manifest and return Path (temp)
    @abstractmethod
    def get_package(
        self,
        name: str,
        version: str,
        toolchain: Toolchain,
    ) -> Path:
        pass


    @abstractmethod
    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        pass


    # Delete package version, return True if file deletion was executed
    @abstractmethod
    def delete(
        self,
        name: str,
        version: str,
    ) -> bool:
        pass


    @abstractmethod
    def upload_component(
        self,
        name: str,
        version: str,
        component: Component,
    ):
        pass


    @abstractmethod
    def list_package_names(self, pattern: str) -> Iterator[str]:
        pass


    # Return all manifest filenames for an exact name+version
    # (e.g. ['boost-1.0-linux-native-manifest.json', 'boost-1.0-native-manifest.json'])
    @abstractmethod
    def list_manifest_names(self, name: str, version: str) -> List[str]:
        pass


    # Identification URL for a package within this service.
    @abstractmethod
    def resource_url(self, pkg: Package) -> str:
        pass


    #
    # Common repository methods
    #

    # Writes a manifest for a 'plain' channel from (filename, checksum) pairs
    def plain_manifest(
        self,
        name: str,
        version: str,
        files: List[Tuple[str, str]],
    ) -> Path:
        manifest_data = {
            'json_version': 5,
            'package': {
                'version_package': name,
                'version_string': version,
                'components': [],
            }
        }
        for filename, checksum in files:
            suffix = None
            if '.' in filename:
                _, suffix = filename.rsplit('.', maxsplit=1)
            manifest_data['package']['components'].append({
                'name':     filename,
                'suffix':   suffix,
                'filename': filename,
                'checksum': checksum,
            })

        localfile = self.tmpdir / f'{name}-{version}-manifest.json'
        with open(localfile, 'w') as fd:
            json.dump(manifest_data, fd, indent=4)

        return localfile


    def list_versions(self, name: str, version: str) -> List[str]:
        if version:
            return [version]

        cached_versions = set(self.cache.get_versions(name))
        remote_versions = set(self.get_versions(name))

        # remove cached versions that are no longer found in the remote
        deleted_versions = set(cached_versions) - set(remote_versions)
        for deleted_version in deleted_versions:
            self.cache.delete(name, deleted_version)
            cached_versions.remove(deleted_version)

        versions = remote_versions

        return sorted(versions, key=version_sort_function, reverse=True)


    def find_package(self, pkg: Package) -> Package:
        localfile = self.cache.get_package(pkg=pkg)
        if not localfile.exists():
            try:
                downloaded = self.get_package(pkg=pkg)
            except LookupError:
                return None
            except Exception:
                raise

            # Add to cache
            localfile.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(downloaded, localfile)

        pkg_out = self.manifest.load(localfile)
        return pkg_out


    def find_components(
        self,
        pkg: Package,
    ) -> Iterator[Component]:
        for comp in pkg.components:
            localfile = self.cache.get_component(pkg, comp)
            if not localfile.exists():
                downloaded = self.get_component(pkg, comp)
                if not downloaded:
                    continue

                # Add to cache
                localfile.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(downloaded, localfile)

            component = copy(comp)
            component.localpath = localfile
            component.sha1sum = compute_sha1sum(localfile)
            yield component

