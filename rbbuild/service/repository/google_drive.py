#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, List, Optional

import requests

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.core.temp_folder import TempFolder
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.oauth2 import OAuth2RefreshAuth
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.rest_helper import RESTHelper
from rbbuild.service.utility import build_path

from .local_file_storage import LocalFileStorage
from .repository import Repository, VersionConflictError

_DEFAULT_URL = 'https://www.googleapis.com/'
_TOKEN_URL = 'https://oauth2.googleapis.com/token'
_FOLDER_MIME = 'application/vnd.google-apps.folder'


# Quotes a value for use in a Drive search query
def _query_string(value: str) -> str:
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


# Google Drive (My Drive or Shared Drive). A package version is stored in
# the folder <root folder>/<root_path>/<name>/<version>, where the root
# folder is the ID given as channel repository.
class GoogleDrive(Repository):
    display_name = 'Google Drive'
    oauth2_supported = True


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
        user_options: dict = None,
    ):
        options = options or {}
        service = channel.remote_service
        if auth_method != AuthMethod.OAUTH2:
            raise SyntaxError(
                f'[profile.services.{service}]: type google_drive requires auth-method "oauth2"'
            )
        # user is the OAuth client ID, credentials the client secret
        refresh_token = (user_options or {}).get('refresh-token')
        if not (user and credentials and refresh_token):
            raise RuntimeError(
                f'{term.bright_white("GoogleDrive")}: user (client ID), credentials '
                f'(client secret) and refresh-token are required for {term.cyan(service)}'
            )

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
        self.auth = OAuth2RefreshAuth(
            self.session, _TOKEN_URL, user, credentials, refresh_token
        )
        self._base_url = (url or _DEFAULT_URL).rstrip('/')
        self._drive_id = options.get('drive-id')
        self._folders = {}
        self.temp_folder = temp_folder
        self.op_mode = op_mode


    @property
    def tmpdir(self):
        return self.temp_folder.path


    def resource_url(self, pkg: Package) -> str:
        return 'gdrive://' + build_path(
            self.channel.repository,
            self.channel.root_path,
            pkg.name,
            pkg.version,
        )


    def _check(self, resp: requests.Response):
        if resp.ok:
            return

        detail = ''
        try:
            detail = f': {resp.json()["error"]["message"]}'
        except (ValueError, KeyError, TypeError):
            pass
        raise requests.exceptions.HTTPError(
            f'{resp.status_code} for {resp.request.method} {resp.url}{detail}',
            response=resp,
        )


    def _api(self, method: str, path: str, headers: dict = None, **kwargs) -> requests.Response:
        params = {'supportsAllDrives': 'true', **kwargs.pop('params', {})}
        resp = self.session.request(
            method,
            f'{self._base_url}/{path}',
            headers={**self.headers, **(headers or {})},
            auth=self.auth,
            params=params,
            **kwargs,
        )
        self._check(resp)
        return resp


    def _list_children(
        self,
        parent_id: str,
        name: str = None,
        folders: Optional[bool] = None,
    ) -> List[dict]:
        query = [f'{_query_string(parent_id)} in parents', 'trashed = false']
        if name is not None:
            query.append(f'name = {_query_string(name)}')
        if folders is not None:
            operator = '=' if folders else '!='
            query.append(f'mimeType {operator} {_query_string(_FOLDER_MIME)}')

        params = {
            'q': ' and '.join(query),
            'fields': 'nextPageToken, files(id, name, sha1Checksum)',
            'pageSize': '1000',
            'includeItemsFromAllDrives': 'true',
        }
        if self._drive_id:
            params.update({'corpora': 'drive', 'driveId': self._drive_id})

        items = []
        while True:
            data = self._api('GET', 'drive/v3/files', params=params).json()
            items.extend(data.get('files', []))
            if not data.get('nextPageToken'):
                return items
            params['pageToken'] = data['nextPageToken']


    def _create_folder(self, parent_id: str, name: str) -> str:
        resp = self._api(
            'POST',
            'drive/v3/files',
            params={'fields': 'id'},
            json={'name': name, 'mimeType': _FOLDER_MIME, 'parents': [parent_id]},
        )
        return resp.json()['id']


    # Returns the ID of the folder at path below root_id (None if it does
    # not exist and create is False)
    def _folder_id(self, root_id: str, path: List[str], create: bool = False) -> Optional[str]:
        parent_id = root_id
        for i, part in enumerate(path):
            key = (root_id, *path[:i + 1])
            folder_id = self._folders.get(key)
            if not folder_id:
                found = self._list_children(parent_id, name=part, folders=True)
                if found:
                    folder_id = found[0]['id']
                elif create:
                    folder_id = self._create_folder(parent_id, part)
                else:
                    return None
                self._folders[key] = folder_id
            parent_id = folder_id
        return parent_id


    def _path(self, channel: Channel, *parts: str) -> List[str]:
        return [p for p in build_path(channel.root_path, *parts).split('/') if p]


    def _files(self, name: str, version: str) -> List[dict]:
        folder_id = self._folder_id(self.channel.repository, self._path(self.channel, name, version))
        if not folder_id:
            return []
        return self._list_children(folder_id, folders=False)


    def _download(self, file_id: str, filename: str) -> Path:
        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        return rest_helper.download_file(
            url=f'{self._base_url}/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true',
            headers=self.headers,
            auth=self.auth,
            filename=filename,
        )


    def list_files(self, name: str, version: str) -> List[str]:
        return [f['name'] for f in self._files(name, version)]


    def list_manifest_names(self, name: str, version: str) -> List[str]:
        suffix = '-manifest.json'
        return sorted(f for f in self.list_files(name, version) if f.endswith(suffix))


    def get_versions(self, name: str) -> List[str]:
        folder_id = self._folder_id(self.channel.repository, self._path(self.channel, name))
        if not folder_id:
            return []
        return [f['name'] for f in self._list_children(folder_id, folders=True)]


    def list_package_names(self, pattern: str) -> Iterator[str]:
        folder_id = self._folder_id(self.channel.repository, self._path(self.channel))
        if not folder_id:
            return

        for item in self._list_children(folder_id, folders=True):
            if pattern and not fnmatch(item['name'], pattern):
                continue
            yield item['name']


    def get_package(self, pkg: Package) -> Path:
        files = {f['name']: f for f in self._files(pkg.name, pkg.version)}
        manifest_path = None

        if self.channel.type == 'rbbuild':
            for legacy in (False, True):
                manifest_fname = self.manifest.make_filename(
                    pkg.name,
                    pkg.version,
                    pkg.toolchain,
                    legacy=legacy,
                )
                if manifest_fname in files:
                    manifest_path = self._download(files[manifest_fname]['id'], manifest_fname)
                    break

        elif self.channel.type == 'plain':
            if files:
                manifest_path = self.plain_manifest(
                    pkg.name,
                    pkg.version,
                    [(f['name'], f.get('sha1Checksum')) for f in files.values()],
                )

        else:
            raise RuntimeError(f'Unknown Google Drive channel type {self.channel.type}')

        if not manifest_path:
            raise LookupError(f'Package not found: {pkg.name}-{pkg.version} ({pkg.toolchain})')

        return manifest_path


    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        for item in self._files(pkg.name, pkg.version):
            if item['name'] == component.filename:
                return self._download(item['id'], component.filename)

        raise LookupError(f'Component not found: {pkg.name}-{pkg.version}/{component.filename}')


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

        folder_id = self._folder_id(
            self.channel.repository,
            self._path(self.channel, name, version),
            create=True,
        )
        if self._list_children(folder_id, name=component.filename, folders=False):
            term.info(f'\r[{term.red("!")}] {component.filename}')
            raise VersionConflictError(
                f'{name}-{version} is already published to channel "{self.channel.name}"'
            )

        resp = self._api(
            'POST',
            'upload/drive/v3/files',
            headers={'X-Upload-Content-Length': str(component.localpath.stat().st_size)},
            params={'uploadType': 'resumable'},
            json={'name': component.filename, 'parents': [folder_id]},
        )
        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        self._check(rest_helper.put_file(
            localfile=component.localpath,
            url=resp.headers['Location'],
            headers=self.headers,
            auth=self.auth,
        ))
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
        filename = localfile.name
        term.info(f'[ ] {filename}', end='')

        source_folder = self._folder_id(
            source_channel.repository,
            self._path(source_channel, name, version),
        )
        source = self._list_children(source_folder, name=filename, folders=False) if source_folder else []
        if not source:
            raise LookupError(f'Component not found: {name}-{version}/{filename}')

        dest_folder = self._folder_id(
            destination_channel.repository,
            self._path(destination_channel, name, version),
            create=not self.op_mode.dry_run,
        )
        existing = self._list_children(dest_folder, name=filename, folders=False) if dest_folder else []

        if existing and not self.op_mode.force:
            term.info(f'\r[{term.yellow("x")}] {filename} ({term.cyan("already exists")})')
            return False

        if self.op_mode.dry_run:
            term.info(f'\r[{term.yellow("x")}] {filename} ({term.cyan("dry run")})')
            return True

        for item in existing:
            self._api('DELETE', f'drive/v3/files/{item["id"]}')
        self._api(
            'POST',
            f'drive/v3/files/{source[0]["id"]}/copy',
            json={'name': filename, 'parents': [dest_folder]},
        )

        term.info(f'\r[{term.green("*")}] {filename}')
        return True


    def delete(
        self,
        name: str,
        version: str,
    ) -> bool:
        folder_id = self._folder_id(self.channel.repository, self._path(self.channel, name, version))
        if not folder_id:
            return False

        self._api('DELETE', f'drive/v3/files/{folder_id}')
        self._folders.clear()
        term.info(f'[{term.green("*")}] Deleted {term.cyan(self.resource_url(Package(name=name, version=version)))}')
        return True
