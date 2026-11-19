#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json
import requests

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Tuple, Iterator

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.core.temp_folder import TempFolder
from rbbuild.librbb.crypto import compute_sha1sum
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.rest_helper import RESTHelper
from rbbuild.service.utility import build_path

from .local_file_storage import LocalFileStorage
from .repository import Repository, VersionConflictError

# HTTP statuses returned by Artifactory when a target path already exists
# and cannot be overwritten (e.g. immutable/release repository policy).
_CONFLICT_STATUS_CODES = (403, 409)


class Artifactory(Repository):
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
        self.CHUNK_BLOCK_SIZE = 65536
        self.temp_folder = temp_folder
        self.op_mode = op_mode


    @property
    def tmpdir(self):
        return self.temp_folder.path


    def resource_url(self, pkg: Package) -> str:
        return self.url + build_path(
            self.channel.repository,
            self.channel.root_path,
            pkg.name,
            pkg.version,
        )


    def aql_request(self, query) -> dict:
        headers = { **self.headers,
                    'Content-Type' : 'text/plain' }
        url = f'{self.url}api/search/aql'

        resp = self.session.post(url=url, headers=headers, auth=self.auth, data=query)
        resp.raise_for_status()

        return resp.json()


    def get_package(self, pkg: Package) -> Path:
        resource_prefix = build_path(self.channel.repository, self.channel.root_path, pkg.name, pkg.version)

        manifest_fname = self.manifest.make_filename(
            pkg.name,
            pkg.version,
            pkg.toolchain,
        )

        manifest_path = None

        if self.channel.type == 'rbbuild':
            rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
            url = f'{self.url}{resource_prefix}/{manifest_fname}'
            manifest_path = rest_helper.download_file(
                url=url,
                headers=self.headers,
                auth=self.auth,
                missing_ok=True,
            )
            # repeat with legacy manifest filename
            if not manifest_path:
                manifest_fname = self.manifest.make_filename(
                    pkg.name,
                    pkg.version,
                    pkg.toolchain,
                    legacy=True,
                )
                url = f'{self.url}{resource_prefix}/{manifest_fname}'
                manifest_path = rest_helper.download_file(
                    url=url,
                    headers=self.headers,
                    auth=self.auth,
                    missing_ok=True,
                )

        elif self.channel.type == 'plain':
            manifest_path = self._generate_plain_manifest(pkg.name, pkg.version)

        elif self.channel.type == 'pypi':
            manifest_path = self._generate_plain_manifest(pkg.name, pkg.version)

        else:
            raise RuntimeError(f'Unknown Artifactory channel type {self.channel.type}')

        if not manifest_path:
            raise LookupError(f'Package not found: {pkg.name}-{pkg.version} ({pkg.toolchain})')

        return manifest_path



    def list_files(self, name: str, version: str) -> List[Tuple[str, str]]:
        query = (
            'items.find({'
               '  "repo" : "%s",'
               '  "type" : "file",'
               '  "path" : "%s"'
               '}).include('
               '  "name",'
               '  "path",'
               '  "actual_sha1",'
               '  "repo"'
               ')'
               % ( self.channel.repository,
                   build_path(self.channel.root_path, name, version) )
        )
        data = self.aql_request(query)

        return [(res.get('name'), res.get('actual_sha1')) for res in data.get('results', {})]


    # Return all manifest filenames for name+version via a single AQL query
    def list_manifest_names(self, name: str, version: str) -> List[str]:
        if self.channel.type == 'pypi':
            return []
        suffix = '-manifest.json'
        return sorted(
            fname for fname, _ in self.list_files(name, version)
            if fname.endswith(suffix)
        )


    def _generate_plain_manifest(self, name: str, version: str) -> Path:
        manifest_data = {
            'json_version': 5,
            'package': {
                'version_package': name,
                'version_string': version,
                'components': [],
            }
        }
        remote_files = self.list_files(name, version)
        for filename, checksum in remote_files:
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


    def get_versions(self, name: str) -> List[str]:
        url = f'{self.url}{build_path("api/storage", self.channel.repository, self.channel.root_path, name)}?list&deep=0&listFolders=1'
        resp = self.session.get(url, headers=self.headers, auth=self.auth)
        if resp.status_code == 404:
            return []

        resp.raise_for_status()

        data = resp.json()
        versions = []
        for entry in data.get('files', []):
            if entry.get('folder') is not True:
                continue

            item = entry.get('uri', '/')[1:]
            versions.append(item)

        return versions


    def list_package_names(self, pattern: str) -> Iterator[str]:
        url = f'{self.url}{build_path("api/storage", self.channel.repository, self.channel.root_path)}?list&deep=0&listFolders=1'
        resp = self.session.get(url, headers=self.headers, auth=self.auth)
        resp.raise_for_status()

        data = resp.json()
        for item in data.get('files', []):
            pkgname = item['uri'][1:]
            if self.channel.type == 'pypi' and pkgname == '.pypi':
                continue
            if pattern:
                if not fnmatch(pkgname, pattern):
                    continue

            yield pkgname


    # Return <version>/<manifest-filename>
    def list_manifests(self, pkgname: str) -> Iterator[str]:
        url = f'{self.url}{build_path("api/storage", self.channel.repository, self.channel.root_path, pkgname)}?list&deep=1'
        resp = self.session.get(url, headers=self.headers, auth=self.auth)
        resp.raise_for_status()

        data = resp.json()
        for item in data.get('files', []):
            if item.get('uri', '').endswith('-manifest.json'):
                yield item['uri'][1:]


    def exists(self, resource: str , dry_run: bool):
        url = f'{self.url}{resource}'
        resp = self.session.head(url=url, headers=self.headers, auth=self.auth)
        if resp.status_code == 404:
            return False

        resp.raise_for_status()
        return True


    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        resource = build_path(self.channel.repository, self.channel.root_path, pkg.name, pkg.version, component.filename)
        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        url = f'{self.url}{resource}'
        localfile = rest_helper.download_file(
            url=url,
            headers=self.headers,
            auth=self.auth,
        )
        return localfile


    def get_sha1sum(self, pkg: Package, comp: Component) -> str:
        sha1sum = None
        query = ( 'items.find({'
            '  "repo" : "%s",'
            '  "type" : "file",'
            '  "path" : "%s",'
            '  "name" : "%s"'
            '}).include('
            '  "name",'
            '  "path",'
            '  "repo",'
            '  "actual_sha1"'
            ')'
            % ( self.channel.repository,
                build_path(self.channel.root_path, pkg.name, pkg.version),
                comp.filename )
            )
        data = self.aql_request(query)
        if data and len(data.get('results', {})) > 0:
            sha1sum = data['results'][0].get('actual_sha1')
        return sha1sum


    def upload_component(
        self,
        name: str,
        version: str,
        component: Component,
    ):
        resource = build_path(self.channel.repository, self.channel.root_path, name, version, component.filename)
        if not component.localpath.exists():
            raise RuntimeError(f'Upload failed. {component.localpath!s} does not exist')

        term.info(f'[ ] {component.filename}', end='')

        if self.op_mode.dry_run is True:
            term.info(f'\r[{term.yellow("x")}] {component.filename} ({term.cyan("dry run")})', end='')
            return True

        if self.exists(resource, dry_run=self.op_mode.dry_run):
            term.info(f'\r[{term.red("!")}] {component.filename}')
            raise VersionConflictError(
                f'{name}-{version} is already published to channel "{self.channel.name}"'
            )

        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        url = f'{self.url}{resource}'

        checksum = component.checksum
        if not checksum:
            checksum = compute_sha1sum(component.localpath)

        headers = {**self.headers, 'X-Checksum-Sha1' : checksum}

        try:
            rest_helper.upload_file(
                localfile=component.localpath,
                checksum=component.checksum,
                url=url,
                headers=headers,
                auth=self.auth,
            )
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in _CONFLICT_STATUS_CODES:
                term.info(f'\r[{term.red("!")}] {component.filename}')
                raise VersionConflictError(
                    f'Conflict publishing {name}-{version} (HTTP {status})'
                ) from e
            raise
        term.info(f'\r[{term.green("*")}] {component.filename}', end='')


    # return True if file was copied, False if copy was skipped
    def copy(
        self,
        localfile: Path,
        name: str,
        version: str,
        source_channel: Channel,
        destination_channel: Channel,
        sha1sum: str,
    ) -> bool:

        source      = build_path(source_channel.repository, source_channel.root_path, name, version, str(localfile))
        destination = build_path(destination_channel.repository, destination_channel.root_path, name, version, str(localfile))

        term.info(f'[ ] {localfile.name}', end='')

        if not self.op_mode.force:
            if self.exists(destination, dry_run=self.op_mode.dry_run):
                term.info(f'\r[{term.yellow("x")}] {localfile.name} ({term.cyan("already exists")})')
                return False

        url = f'{self.url}api/copy/{source}?to={destination}'
        if self.op_mode.dry_run:
            msg = f'\r[{term.yellow("x")}] {localfile.name} ({term.cyan("dry run")})'
            url += '&dry=1'
        else:
            msg = f'\r[{term.green("*")}] {localfile.name}'

        resp = self.session.post(url=url, headers=self.headers, auth=self.auth, data=None)
        resp.raise_for_status()

        term.info(msg)
        return True


    def delete(
        self,
        name: str,
        version: str,
    ) -> bool:
        resource = build_path(self.channel.repository, self.channel.root_path, name, version)
        url = f'{self.url}{resource}'

        resp = self.session.delete(url=url, headers=self.headers, auth=self.auth)
        resp.raise_for_status()
        term.info(f'[{term.green("*")}] Deleted {term.cyan(url)}')

