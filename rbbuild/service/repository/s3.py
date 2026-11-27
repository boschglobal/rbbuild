#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import xml.etree.ElementTree as ET

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import quote

import requests

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.core.temp_folder import TempFolder
from rbbuild.librbb.crypto import compute_sha256sum
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.rest_helper import RESTHelper
from rbbuild.service.sigv4 import SigV4Auth
from rbbuild.service.utility import build_path

from .local_file_storage import LocalFileStorage
from .repository import Repository, VersionConflictError

# HTTP statuses returned by S3 when an object cannot be overwritten
_CONFLICT_STATUS_CODES = (409, 412)

# Region sent for signing if the service does not define one. Most
# S3-compatible services accept it.
_DEFAULT_REGION = 'us-east-1'


def _local_name(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _child_text(element: ET.Element, name: str) -> Optional[str]:
    for child in element:
        if _local_name(child.tag) == name:
            return child.text
    return None


# Amazon S3 and S3-compatible services (path-style addressing)
class S3(Repository):
    display_name = 'S3'


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
        options: dict = None,
    ):
        if not url:
            raise SyntaxError(
                f'[profile.services.{channel.remote_service}]: url is required for type s3'
            )
        if not user or not credentials:
            raise RuntimeError(
                f'{term.bright_white("S3")}: missing access key (user) or secret key '
                f'(credentials) for {term.cyan(channel.remote_service)}'
            )

        # S3 is always authenticated with SigV4, regardless of auth-method
        Repository.__init__(
            self,
            channel=channel,
            cache=cache,
            manifest=manifest,
            url=url,
            auth_method=AuthMethod.NONE,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        region = (options or {}).get('region', _DEFAULT_REGION)
        self.auth = SigV4Auth(user, credentials, region)
        self._identity = (user, credentials, region)
        self._base_url = url.rstrip('/')
        self.temp_folder = temp_folder
        self.op_mode = op_mode


    @property
    def tmpdir(self):
        return self.temp_folder.path


    # A server-side copy is signed with the credentials of this service only
    def can_copy_to(self, other: Repository) -> bool:
        return super().can_copy_to(other) and self._identity == other._identity


    def _object_url(self, repository: str, key: str = '') -> str:
        return f'{self._base_url}/{quote(build_path(repository, key))}'


    def _key(self, name: str, version: str, filename: str = None) -> str:
        return build_path(self.channel.root_path, name, version, filename)


    def resource_url(self, pkg: Package) -> str:
        return self._object_url(self.channel.repository, self._key(pkg.name, pkg.version))


    # S3 error bodies name the cause (e.g., the expected region)
    def _check(self, resp: requests.Response):
        if resp.ok:
            return

        detail = ''
        try:
            root = ET.fromstring(resp.content)
            detail = f': {_child_text(root, "Code")} - {_child_text(root, "Message")}'
        except ET.ParseError:
            pass
        raise requests.exceptions.HTTPError(
            f'{resp.status_code} for {resp.request.method} {resp.url}{detail}',
            response=resp,
        )


    # Returns (keys, common prefixes) below prefix
    def _list(self, prefix: str, delimiter: str = None) -> Tuple[List[str], List[str]]:
        keys = []
        prefixes = []
        token = None
        while True:
            params = {'list-type': '2', 'prefix': prefix}
            if delimiter:
                params['delimiter'] = delimiter
            if token:
                params['continuation-token'] = token
            query = '&'.join(f'{k}={quote(v, safe="")}' for k, v in params.items())

            resp = self.session.get(
                f'{self._object_url(self.channel.repository)}?{query}',
                headers=self.headers,
                auth=self.auth,
            )
            self._check(resp)

            root = ET.fromstring(resp.content)
            for element in root:
                tag = _local_name(element.tag)
                if tag == 'Contents':
                    keys.append(_child_text(element, 'Key'))
                elif tag == 'CommonPrefixes':
                    prefixes.append(_child_text(element, 'Prefix'))

            if _child_text(root, 'IsTruncated') != 'true':
                break
            token = _child_text(root, 'NextContinuationToken')

        return keys, prefixes


    # Returns file names directly below name/version
    def list_files(self, name: str, version: str) -> List[str]:
        prefix = self._key(name, version) + '/'
        keys, _ = self._list(prefix)
        return [k[len(prefix):] for k in keys if '/' not in k[len(prefix):]]


    def list_manifest_names(self, name: str, version: str) -> List[str]:
        suffix = '-manifest.json'
        return sorted(f for f in self.list_files(name, version) if f.endswith(suffix))


    def get_versions(self, name: str) -> List[str]:
        prefix = build_path(self.channel.root_path, name) + '/'
        _, prefixes = self._list(prefix, delimiter='/')
        return [p[len(prefix):].rstrip('/') for p in prefixes]


    def list_package_names(self, pattern: str) -> Iterator[str]:
        prefix = build_path(self.channel.root_path)
        if prefix:
            prefix += '/'
        _, prefixes = self._list(prefix, delimiter='/')
        for item in prefixes:
            pkgname = item[len(prefix):].rstrip('/')
            if pattern and not fnmatch(pkgname, pattern):
                continue
            yield pkgname


    def get_package(self, pkg: Package) -> Path:
        manifest_path = None

        if self.channel.type == 'rbbuild':
            rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
            for legacy in (False, True):
                manifest_fname = self.manifest.make_filename(
                    pkg.name,
                    pkg.version,
                    pkg.toolchain,
                    legacy=legacy,
                )
                manifest_path = rest_helper.download_file(
                    url=self._object_url(
                        self.channel.repository,
                        self._key(pkg.name, pkg.version, manifest_fname),
                    ),
                    headers=self.headers,
                    auth=self.auth,
                    missing_ok=True,
                )
                if manifest_path:
                    break

        elif self.channel.type == 'plain':
            files = [(f, None) for f in self.list_files(pkg.name, pkg.version)]
            if files:
                manifest_path = self.plain_manifest(pkg.name, pkg.version, files)

        else:
            raise RuntimeError(f'Unknown S3 channel type {self.channel.type}')

        if not manifest_path:
            raise LookupError(f'Package not found: {pkg.name}-{pkg.version} ({pkg.toolchain})')

        return manifest_path


    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        return rest_helper.download_file(
            url=self._object_url(
                self.channel.repository,
                self._key(pkg.name, pkg.version, component.filename),
            ),
            headers=self.headers,
            auth=self.auth,
        )


    def exists(self, url: str) -> bool:
        resp = self.session.head(url, headers=self.headers, auth=self.auth)
        if resp.status_code == 404:
            return False
        self._check(resp)
        return True


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

        url = self._object_url(
            self.channel.repository,
            self._key(name, version, component.filename),
        )
        if self.exists(url):
            term.info(f'\r[{term.red("!")}] {component.filename}')
            raise VersionConflictError(
                f'{name}-{version} is already published to channel "{self.channel.name}"'
            )

        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        headers = {
            **self.headers,
            'x-amz-content-sha256': compute_sha256sum(component.localpath),
        }
        resp = rest_helper.put_file(
            localfile=component.localpath,
            url=url,
            headers=headers,
            auth=self.auth,
        )
        if resp.status_code in _CONFLICT_STATUS_CODES:
            term.info(f'\r[{term.red("!")}] {component.filename}')
            raise VersionConflictError(
                f'Conflict publishing {name}-{version} (HTTP {resp.status_code})'
            )
        self._check(resp)
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
        source_key = build_path(source_channel.root_path, name, version, localfile.name)
        dest_key = build_path(destination_channel.root_path, name, version, localfile.name)
        dest_url = self._object_url(destination_channel.repository, dest_key)

        term.info(f'[ ] {localfile.name}', end='')

        if not self.op_mode.force:
            if self.exists(dest_url):
                term.info(f'\r[{term.yellow("x")}] {localfile.name} ({term.cyan("already exists")})')
                return False

        if self.op_mode.dry_run:
            term.info(f'\r[{term.yellow("x")}] {localfile.name} ({term.cyan("dry run")})')
            return True

        headers = {
            **self.headers,
            'x-amz-copy-source': quote(build_path(source_channel.repository, source_key)),
        }
        resp = self.session.put(dest_url, headers=headers, auth=self.auth)
        self._check(resp)
        # S3 may report a failed copy in the body of a 200 response
        if b'<Error>' in resp.content:
            raise RuntimeError(f'Copy of {localfile.name} failed: {resp.text}')

        term.info(f'\r[{term.green("*")}] {localfile.name}')
        return True


    def delete(
        self,
        name: str,
        version: str,
    ) -> bool:
        prefix = self._key(name, version) + '/'
        keys, _ = self._list(prefix)
        for key in keys:
            resp = self.session.delete(
                self._object_url(self.channel.repository, key),
                headers=self.headers,
                auth=self.auth,
            )
            self._check(resp)

        url = self._object_url(self.channel.repository, self._key(name, version))
        term.info(f'[{term.green("*")}] Deleted {term.cyan(url)}')
        return bool(keys)
