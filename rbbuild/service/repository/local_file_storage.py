#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import os.path
import shutil

from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Iterator

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.core.temp_folder import TempFolder
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package

from .repository import Repository, VersionConflictError


class LocalFileStorage:
    def __init__(
        self,
        channel: Channel,
        dist_path: Path,
        manifest: Manifest,
    ):
        self.base_path = Path(dist_path) / channel.remote_service / channel.repository / channel.root_path
        self.channel = channel
        self.manifest = manifest


    def get_package(self, pkg: Package) -> Path:
        pkg_path = self.base_path / pkg.name

        manifest_path = pkg_path / pkg.version / self.manifest.make_filename(
            pkg.name,
            pkg.version,
            pkg.toolchain,
        )

        if not manifest_path.exists():
            manifest_path = pkg_path / pkg.version / self.manifest.make_filename(
                pkg.name,
                pkg.version,
                pkg.toolchain,
                legacy=True,
            )

        return manifest_path


    # Return all manifest filenames present in the local cache for name+version
    def list_manifest_names(self, name: str, version: str) -> List[str]:
        pkg_dir = self.base_path / name / version
        if not pkg_dir.is_dir():
            return []
        suffix = '-manifest.json'
        return sorted(f.name for f in pkg_dir.iterdir() if f.name.endswith(suffix))


    def get_versions(self, name: str) -> List[str]:
        pkg_path = self.base_path / name

        if not pkg_path.exists():
            return []

        versions = []
        for item in pkg_path.iterdir():
            if not item.is_dir():
                continue

            versions.append(item.name)

        return versions


    def get_component(self, pkg: Package, component: Component) -> Path:
        comp_path = self.base_path / pkg.name / pkg.version / component.filename
        return comp_path


    def delete(
        self,
        name: str,
        version: str,
    ):
        pkg_path = self.base_path / name / version

        term.debug(f'cache {self.channel.name}', f'Deleting resource {pkg_path!s}')
        if pkg_path.exists():
            shutil.rmtree(pkg_path)
            return True

        return False


    def deploy_file(
        self,
        localfile: Path,
        checksum: str,
        target: str,
        from_temp: bool=False,
    ) -> Path:

        # Allow rename of localfile on target
        if target.endswith(os.path.sep):
            dest = self.base_path / target
            dest_file = dest / localfile.name
        else:
            dest_file = self.base_path / target
            dest = dest_file.parent

        dest.mkdir(exist_ok=True, parents=True)

        # Move instead of copy
        if from_temp is True:
            localfile.replace(dest_file)
        else:
            shutil.copy(localfile, dest_file)

        return dest_file


class LocalFileService(LocalFileStorage, Repository):
    def __init__(
        self,
        channel: Channel,
        url: str,
        user: str,
        credentials: str,
        auth_method,
        cache,
        manifest: Manifest,
        temp_folder: TempFolder,
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

        u = urlparse(url)
        assert(u.scheme == 'file')

        if not Path(u.path).is_dir():
            term.warning(f'Local file service {url}', 'Path does not exist')

        LocalFileStorage.__init__(
            self,
            channel=channel,
            dist_path=u.path,
            manifest=manifest
        )

        self.temp_folder = temp_folder
        self.op_mode = op_mode


    @property
    def tmpdir(self):
        return self.temp_folder.path


    def resource_url(self, pkg: Package) -> str:
        return pkg.url


    def get_package(self, pkg: Package) -> Path:
        pkg_path = LocalFileStorage.get_package(self, pkg=pkg)

        if not pkg_path.exists():
            raise LookupError(f'Package not found: {pkg.name}-{pkg.version} ({pkg.toolchain})')

        localfile = self.tmpdir / pkg_path.name
        shutil.copy(pkg_path, localfile)
        return localfile


    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        comp_path = LocalFileStorage.get_component(self, pkg=pkg, component=component)
        localfile = self.tmpdir / component.filename
        shutil.copy(comp_path, localfile)
        return localfile


    def upload_component(
        self,
        name: str,
        version: str,
        component: Component,
    ):
        if not component.localpath.exists():
            raise RuntimeError(f'Upload failed. {component.localpath!s} does not exist')

        term.info(f'[ ] {component.filename}', end='')

        if self.op_mode.dry_run is True:
            term.info(f'\r[{term.yellow("x")}] {component.filename} ({term.cyan("dry run")})', end='')
            return True

        target = f'{name}/{version}/{component.filename}'
        if (self.base_path / target).exists():
            term.info(f'\r[{term.red("!")}] {component.filename}')
            raise VersionConflictError(
                f'{name}-{version} is already published to channel "{self.channel.name}"'
            )

        self.deploy_file(component.localpath, component.checksum, target)
        term.info(f'\r[{term.green("*")}] {component.filename}', end='')


    def list_package_names(self, pattern: str) -> Iterator[str]:
        if not self.base_path.is_dir():
            return

        for item in sorted(self.base_path.iterdir(), key=lambda p: p.name):
            if not item.is_dir():
                continue

            if pattern:
                if not fnmatch(pattern, item.name):
                    continue
            yield item.name

