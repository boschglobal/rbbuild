# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import itertools
import json
import re

from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from rbbuild.package.component import Component
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.repository.google_drive import GoogleDrive, _query_string
from rbbuild.service.repository.repository import VersionConflictError

# Unit tests for the GoogleDrive repository against a small fake of the
# Drive v3 API (folders, files, upload sessions, copy and delete).

_API = 'https://www.googleapis.com'


class _FakeDrive:
    def __init__(self, requests_mock):
        self.items = {}
        self.upload_sessions = {}
        self._ids = itertools.count(1)
        self.list_requests = []
        self.token = requests_mock.post(
            'https://oauth2.googleapis.com/token',
            json={'access_token': 'tok', 'expires_in': 3600},
        )
        requests_mock.get(f'{_API}/drive/v3/files', json=self._list)
        requests_mock.post(f'{_API}/drive/v3/files', json=self._create)
        requests_mock.post(f'{_API}/upload/drive/v3/files', text=self._session)
        requests_mock.put(re.compile(r'https://upload\.example\.test/'), json=self._upload)
        requests_mock.get(re.compile(rf'{_API}/drive/v3/files/[^/?]+\?'), content=self._download)
        requests_mock.post(re.compile(rf'{_API}/drive/v3/files/[^/?]+/copy'), json=self._copy)
        requests_mock.delete(re.compile(rf'{_API}/drive/v3/files/[^/?]+'), status_code=204, text=self._delete)


    def add(self, name, parent, folder=False, content=b'', sha1=None):
        item_id = f'id{next(self._ids)}'
        self.items[item_id] = {
            'id': item_id, 'name': name, 'parent': parent, 'folder': folder,
            'content': content, 'sha1Checksum': sha1,
        }
        return item_id


    def path(self, root, *parts):
        parent = root
        for part in parts:
            parent = next(
                i['id'] for i in self.items.values()
                if i['parent'] == parent and i['name'] == part and i['folder'])
        return parent


    def files_in(self, folder_id):
        return {i['name']: i['content'] for i in self.items.values()
                if i['parent'] == folder_id and not i['folder']}


    def _list(self, request, context):
        self.list_requests.append(parse_qs(urlsplit(request.url).query))
        q = self.list_requests[-1]['q'][0]
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
        name = name.group(1).replace("\\'", "'").replace('\\\\', '\\') if name else None
        mime = re.search(r"mimeType (!?=)", q)
        result = []
        for item in self.items.values():
            if item['parent'] != parent:
                continue
            if name is not None and item['name'] != name:
                continue
            if mime and (item['folder'] != (mime.group(1) == '=')):
                continue
            result.append({k: item[k] for k in ('id', 'name', 'sha1Checksum')})
        return {'files': result}


    def _create(self, request, context):
        body = request.json()
        return {'id': self.add(body['name'], body['parents'][0], folder=True)}


    def _session(self, request, context):
        body = request.json()
        session = f'https://upload.example.test/s{len(self.upload_sessions)}'
        self.upload_sessions[session] = body
        context.headers['Location'] = session
        return ''


    def _upload(self, request, context):
        body = self.upload_sessions[request.url]
        content = request.body.read() if hasattr(request.body, 'read') else request.body
        return {'id': self.add(body['name'], body['parents'][0], content=content or b'')}


    def _download(self, request, context):
        item_id = urlsplit(request.url).path.rsplit('/', 1)[-1]
        return self.items[item_id]['content']


    def _copy(self, request, context):
        item_id = urlsplit(request.url).path.split('/')[-2]
        body = request.json()
        src = self.items[item_id]
        return {'id': self.add(body['name'], body['parents'][0], content=src['content'])}


    def _delete(self, request, context):
        item_id = urlsplit(request.url).path.rsplit('/', 1)[-1]
        doomed = {item_id}
        changed = True
        while changed:
            changed = False
            for item in self.items.values():
                if item['parent'] in doomed and item['id'] not in doomed:
                    doomed.add(item['id'])
                    changed = True
        for i in doomed:
            del self.items[i]
        return ''


@pytest.fixture
def drive(requests_mock):
    return _FakeDrive(requests_mock)


def _make_drive(tmp_path, chtype='rbbuild', root_path='', options=None,
                force=False, dry_run=False, auth_method=AuthMethod.OAUTH2,
                user='cid', credentials='csecret', refresh_token='rtoken',
                url=None, repository='root1'):
    channel = MagicMock(
        remote_service='svc', repository=repository, root_path=root_path, type=chtype)
    channel.name = 'development'
    manifest = MagicMock()
    manifest.make_filename.side_effect = (
        lambda name, version, toolchain, legacy=False:
        f'{name}-{version}{"-legacy" if legacy else ""}-manifest.json')
    return GoogleDrive(
        channel=channel,
        cache=MagicMock(),
        manifest=manifest,
        temp_folder=MagicMock(path=tmp_path),
        url=url,
        auth_method=auth_method,
        user=user,
        credentials=credentials,
        op_mode=MagicMock(force=force, dry_run=dry_run),
        truststore=False,
        options=options,
        user_options={'refresh-token': refresh_token} if refresh_token else {},
    )


def _component(tmp_path, filename='pkg-1.0.tar', data=b'data'):
    localpath = tmp_path / filename
    localpath.write_bytes(data)
    return Component(name='pkg', suffix='tar', filename=filename, localpath=localpath)


def test_query_string_escapes_quote_and_backslash():
    assert _query_string("it's a\\b") == "'it\\'s a\\\\b'"


def test_auth_method_oauth2_is_required(tmp_path):
    with pytest.raises(SyntaxError, match='svc.*requires auth-method "oauth2"'):
        _make_drive(tmp_path, auth_method=AuthMethod.BEARER_TOKEN)


@pytest.mark.parametrize('user, credentials, refresh_token', [
    (None, 'csecret', 'rtoken'),
    ('cid', None, 'rtoken'),
    ('cid', 'csecret', None),
])
def test_client_credentials_and_refresh_token_are_required(
    tmp_path, user, credentials, refresh_token
):
    with pytest.raises(RuntimeError, match='client ID.*client secret.*refresh-token'):
        _make_drive(
            tmp_path, user=user, credentials=credentials, refresh_token=refresh_token)


def test_requests_carry_refreshed_bearer_token(tmp_path, drive, requests_mock):
    _make_drive(tmp_path).get_versions('pkg')

    assert requests_mock.request_history[-1].headers['Authorization'] == 'Bearer tok'
    assert drive.token.last_request.text == (
        'grant_type=refresh_token&client_id=cid'
        '&client_secret=csecret&refresh_token=rtoken')


def test_access_token_is_reused(tmp_path, drive):
    service = _make_drive(tmp_path)

    service.get_versions('pkg')
    service.get_versions('other')

    assert drive.token.call_count == 1


def test_url_option_overrides_default_endpoint(tmp_path, requests_mock):
    requests_mock.post('https://oauth2.googleapis.com/token', json={'access_token': 't'})
    listing = requests_mock.get('https://drive.example.test/drive/v3/files', json={'files': []})

    _make_drive(tmp_path, url='https://drive.example.test/').get_versions('pkg')

    assert listing.called


def test_requests_support_shared_drives(tmp_path, drive):
    _make_drive(tmp_path).get_versions('pkg')

    query = drive.list_requests[-1]
    assert query['supportsAllDrives'] == ['true']
    assert query['includeItemsFromAllDrives'] == ['true']
    assert 'driveId' not in query


def test_drive_id_option_restricts_corpus(tmp_path, drive):
    _make_drive(tmp_path, options={'drive-id': 'shared1'}).get_versions('pkg')

    query = drive.list_requests[-1]
    assert query['corpora'] == ['drive']
    assert query['driveId'] == ['shared1']


def test_get_versions_follows_nested_root_path(tmp_path, drive):
    root_path = drive.add('a', 'root1', folder=True)
    b = drive.add('b', root_path, folder=True)
    pkg = drive.add('pkg', b, folder=True)
    drive.add('1.0', pkg, folder=True)
    drive.add('2.0', pkg, folder=True)
    drive.add('notes.txt', pkg)

    assert sorted(_make_drive(tmp_path, root_path='a/b').get_versions('pkg')) == ['1.0', '2.0']


def test_get_versions_of_unknown_package_is_empty(tmp_path, drive):
    assert _make_drive(tmp_path).get_versions('pkg') == []


def test_list_package_names_filters_by_pattern(tmp_path, drive):
    drive.add('boost', 'root1', folder=True)
    drive.add('zlib', 'root1', folder=True)

    assert list(_make_drive(tmp_path).list_package_names('b*')) == ['boost']
    assert sorted(_make_drive(tmp_path).list_package_names(None)) == ['boost', 'zlib']


def test_list_package_names_without_root_folder_is_empty(tmp_path, drive):
    assert list(_make_drive(tmp_path, root_path='missing').list_package_names(None)) == []


def test_list_manifest_names(tmp_path, drive):
    pkg = drive.add('pkg', 'root1', folder=True)
    ver = drive.add('1.0', pkg, folder=True)
    drive.add('pkg-1.0-linux-manifest.json', ver)
    drive.add('pkg-1.0.tar', ver)

    assert _make_drive(tmp_path).list_manifest_names('pkg', '1.0') == [
        'pkg-1.0-linux-manifest.json']


def _add_version(drive, name='pkg', version='1.0', root='root1'):
    pkg = drive.add(name, root, folder=True)
    return drive.add(version, pkg, folder=True)


def _add_destination(drive, content):
    prod = drive.add('prod', 'root2', folder=True)
    pkg = drive.add('pkg', prod, folder=True)
    ver = drive.add('1.0', pkg, folder=True)
    drive.add('pkg-1.0.tar', ver, content=content)
    return ver


def test_get_package_downloads_manifest(tmp_path, drive):
    drive.add('pkg-1.0-manifest.json', _add_version(drive), content=b'{}')

    path = _make_drive(tmp_path).get_package(Package(name='pkg', version='1.0'))

    assert path.name == 'pkg-1.0-manifest.json'
    assert path.read_bytes() == b'{}'


def test_get_package_falls_back_to_legacy_manifest(tmp_path, drive):
    drive.add('pkg-1.0-legacy-manifest.json', _add_version(drive), content=b'{}')

    path = _make_drive(tmp_path).get_package(Package(name='pkg', version='1.0'))

    assert path.name == 'pkg-1.0-legacy-manifest.json'


def test_get_package_missing_raises_lookup_error(tmp_path, drive):
    with pytest.raises(LookupError, match='pkg-1.0'):
        _make_drive(tmp_path).get_package(Package(name='pkg', version='1.0'))


def test_get_package_of_plain_channel_uses_drive_checksums(tmp_path, drive):
    drive.add('pkg-1.0.tar.gz', _add_version(drive), content=b'x', sha1='abc123')

    path = _make_drive(tmp_path, chtype='plain').get_package(
        Package(name='pkg', version='1.0'))

    components = json.loads(path.read_text())['package']['components']
    assert components[0]['filename'] == 'pkg-1.0.tar.gz'
    assert components[0]['checksum'] == 'abc123'


def test_get_package_of_unknown_channel_type_raises(tmp_path, drive):
    with pytest.raises(RuntimeError, match='Unknown Google Drive channel type pypi'):
        _make_drive(tmp_path, chtype='pypi').get_package(Package(name='pkg', version='1.0'))


def test_get_component_downloads_file(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'data')
    comp = Component(name='pkg', suffix='tar', filename='pkg-1.0.tar')

    path = _make_drive(tmp_path).get_component(Package(name='pkg', version='1.0'), comp)

    assert path.name == 'pkg-1.0.tar'
    assert path.read_bytes() == b'data'


def test_get_component_missing_raises_lookup_error(tmp_path, drive):
    _add_version(drive)
    comp = Component(name='pkg', suffix='tar', filename='pkg-1.0.tar')

    with pytest.raises(LookupError, match='pkg-1.0.tar'):
        _make_drive(tmp_path).get_component(Package(name='pkg', version='1.0'), comp)


def test_upload_creates_folders_and_uploads_file(tmp_path, drive):
    _make_drive(tmp_path, root_path='comp').upload_component(
        'pkg', '1.0', _component(tmp_path))

    folder = drive.path('root1', 'comp', 'pkg', '1.0')
    assert drive.files_in(folder) == {'pkg-1.0.tar': b'data'}


def test_upload_of_empty_file(tmp_path, drive):
    _make_drive(tmp_path).upload_component(
        'pkg', '1.0', _component(tmp_path, data=b''))

    assert drive.files_in(drive.path('root1', 'pkg', '1.0')) == {'pkg-1.0.tar': b''}


def test_upload_session_announces_size(tmp_path, drive, requests_mock):
    _make_drive(tmp_path).upload_component('pkg', '1.0', _component(tmp_path))

    init = next(r for r in requests_mock.request_history
                if r.url.startswith(f'{_API}/upload/'))
    assert init.headers['X-Upload-Content-Length'] == '4'
    assert parse_qs(urlsplit(init.url).query)['uploadType'] == ['resumable']


def test_upload_of_existing_file_raises_conflict(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'old')

    with pytest.raises(VersionConflictError):
        _make_drive(tmp_path, force=True).upload_component(
            'pkg', '1.0', _component(tmp_path))

    assert drive.files_in(drive.path('root1', 'pkg', '1.0')) == {'pkg-1.0.tar': b'old'}


def test_upload_error_propagates(tmp_path, drive, requests_mock):
    requests_mock.put(
        re.compile(r'https://upload\.example\.test/'),
        status_code=403,
        json={'error': {'message': 'The user does not have sufficient permissions'}},
    )

    with pytest.raises(requests.exceptions.HTTPError, match='sufficient permissions'):
        _make_drive(tmp_path).upload_component('pkg', '1.0', _component(tmp_path))


def test_upload_dry_run_sends_nothing(tmp_path, drive, requests_mock):
    result = _make_drive(tmp_path, dry_run=True).upload_component(
        'pkg', '1.0', _component(tmp_path))

    assert result is True
    assert requests_mock.call_count == 0


def _channel(repository, root_path=''):
    return MagicMock(repository=repository, root_path=root_path)


def _copy(drive_service, **kwargs):
    return drive_service.copy(
        localfile=Path('pkg-1.0.tar'), name='pkg', version='1.0',
        source_channel=_channel('root1'),
        destination_channel=_channel('root2', 'prod'),
        sha1sum=None, **kwargs)


def test_copy_creates_destination_and_copies_file(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'data')

    assert _copy(_make_drive(tmp_path)) is True

    folder = drive.path('root2', 'prod', 'pkg', '1.0')
    assert drive.files_in(folder) == {'pkg-1.0.tar': b'data'}


def test_copy_skips_existing_destination(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'new')
    ver = _add_destination(drive, b'old')

    assert _copy(_make_drive(tmp_path)) is False
    assert drive.files_in(ver) == {'pkg-1.0.tar': b'old'}


def test_copy_with_force_replaces_existing_file(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'new')
    ver = _add_destination(drive, b'old')

    assert _copy(_make_drive(tmp_path, force=True)) is True
    assert drive.files_in(ver) == {'pkg-1.0.tar': b'new'}


def test_copy_dry_run_changes_nothing(tmp_path, drive):
    drive.add('pkg-1.0.tar', _add_version(drive), content=b'data')

    assert _copy(_make_drive(tmp_path, dry_run=True)) is True
    assert not any(i['parent'] == 'root2' for i in drive.items.values())


def test_copy_of_missing_source_raises(tmp_path, drive):
    with pytest.raises(LookupError, match='pkg-1.0/pkg-1.0.tar'):
        _copy(_make_drive(tmp_path))


def test_delete_removes_version_folder(tmp_path, drive):
    version = _add_version(drive)
    drive.add('pkg-1.0.tar', version)
    other = drive.add('2.0', drive.path('root1', 'pkg'), folder=True)

    assert _make_drive(tmp_path).delete('pkg', '1.0') is True

    assert version not in drive.items
    assert other in drive.items


def test_delete_of_missing_version_returns_false(tmp_path, drive):
    assert _make_drive(tmp_path).delete('pkg', '1.0') is False


def test_resource_url(tmp_path):
    pkg = Package(name='pkg', version='1.0')

    assert _make_drive(tmp_path, root_path='comp').resource_url(pkg) == (
        'gdrive://root1/comp/pkg/1.0')
