# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re
from unittest.mock import MagicMock

import pytest
import requests

from rbbuild.package.component import Component
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.repository.artifactory import Artifactory
from rbbuild.service.repository.url_service import URLService
from rbbuild.service.rest_helper import RESTHelper

_URL = 'https://example.test/artifactory/repo/pkg/1.0/file.tar.xz'
_ANY_URL = re.compile(r'^https://example\.test/')


def _helper(tmp_path):
    return RESTHelper(
        tmp_path, session=requests.Session(), progress_cb=lambda *_: None
    )


# By default, any HTTP error - including 404 - raises. An invalid
# dependency URL must never be silently skipped.
def test_download_file_404_raises_by_default(tmp_path, requests_mock):
    requests_mock.get(_URL, status_code=404)

    with pytest.raises(requests.exceptions.HTTPError):
        _helper(tmp_path).download_file(_URL, headers={}, auth=None)


def test_download_file_missing_ok_returns_none_on_404(tmp_path, requests_mock):
    requests_mock.get(_URL, status_code=404)

    result = _helper(tmp_path).download_file(
        _URL, headers={}, auth=None, missing_ok=True)

    assert result is None
    assert not (tmp_path / 'file.tar.xz').exists()


# missing_ok only covers 404; other errors still propagate.
@pytest.mark.parametrize('status_code', [401, 403, 500])
def test_download_file_missing_ok_raises_on_other_errors(
    tmp_path, requests_mock, status_code
):
    requests_mock.get(_URL, status_code=status_code)

    with pytest.raises(requests.exceptions.HTTPError):
        _helper(tmp_path).download_file(
            _URL, headers={}, auth=None, missing_ok=True)


def test_download_file_success(tmp_path, requests_mock):
    requests_mock.get(_URL, content=b'data')

    result = _helper(tmp_path).download_file(
        _URL, headers={}, auth=None, missing_ok=True)

    assert result.read_bytes() == b'data'


def test_download_file_uses_given_session(tmp_path):
    session = MagicMock()
    session.get.return_value.__enter__.return_value = MagicMock(
        ok=True, headers={}, iter_content=lambda chunk_size: [b'data']
    )
    helper = RESTHelper(tmp_path, session=session, progress_cb=lambda *_: None)

    helper.download_file(_URL, headers={}, auth=None)

    session.get.assert_called_once()


# ---------------------------------------------------------------------------
# Services built on RESTHelper
# ---------------------------------------------------------------------------

def _make_artifactory(tmp_path, channel_type='rbbuild'):
    manifest = MagicMock()
    manifest.make_filename.side_effect = (
        lambda name, version, toolchain, legacy=False:
            f'{name}-{version}-{"legacy-" if legacy else ""}manifest.json')
    return Artifactory(
        channel=MagicMock(
            type=channel_type, repository='repo', root_path='components'),
        cache=MagicMock(),
        manifest=manifest,
        temp_folder=MagicMock(path=tmp_path),
        url='https://example.test/artifactory/',
        auth_method=AuthMethod.NONE,
        user=None,
        credentials=None,
        op_mode=MagicMock(),
        truststore=False,
    )


_MANIFEST_BASE = (
    'https://example.test/artifactory/repo/components/pkg/1.0/')


# A manifest that is missing in the channel is "not found" (LookupError), so
# find_package() returns None and the next channel can be searched.
def test_artifactory_get_package_missing_manifest_raises_lookup_error(
    tmp_path, requests_mock
):
    requests_mock.get(_ANY_URL, status_code=404)
    repo = _make_artifactory(tmp_path)

    with pytest.raises(LookupError):
        repo.get_package(Package(name='pkg', version='1.0'))


# The legacy manifest filename is tried when the current one is missing.
def test_artifactory_get_package_falls_back_to_legacy_name(
    tmp_path, requests_mock
):
    requests_mock.get(_ANY_URL, status_code=404)
    requests_mock.get(f'{_MANIFEST_BASE}pkg-1.0-legacy-manifest.json', text='{}')
    repo = _make_artifactory(tmp_path)

    result = repo.get_package(Package(name='pkg', version='1.0'))

    assert result.name == 'pkg-1.0-legacy-manifest.json'


# Server errors while looking up a manifest are not "not found".
def test_artifactory_get_package_server_error_propagates(
    tmp_path, requests_mock
):
    requests_mock.get(_ANY_URL, status_code=500)
    repo = _make_artifactory(tmp_path)

    with pytest.raises(requests.exceptions.HTTPError):
        repo.get_package(Package(name='pkg', version='1.0'))


# A component file missing on the server is an error, not a silent skip.
def test_artifactory_get_component_404_raises(tmp_path, requests_mock):
    requests_mock.get(_ANY_URL, status_code=404)
    repo = _make_artifactory(tmp_path)
    comp = Component(name='dev', suffix='tar.xz', filename='file.tar.xz')

    with pytest.raises(requests.exceptions.HTTPError):
        repo.get_component(Package(name='pkg', version='1.0'), comp)


# An invalid dependency URL (e.g. in rbbuild.toml) must raise when its
# component is downloaded, instead of finishing without any download.
def test_url_service_get_component_404_raises(tmp_path, requests_mock):
    requests_mock.get(_URL, status_code=404)
    service = URLService(
        channel=MagicMock(),
        manifest=MagicMock(),
        temp_folder=MagicMock(path=tmp_path),
        url=None,
        user=None,
        auth_method=AuthMethod.NONE,
        cache=MagicMock(),
        credentials=None,
        truststore=False,
    )
    pkg = Package(name='pkg', version='1.0')
    pkg.url = _URL

    with pytest.raises(requests.exceptions.HTTPError):
        service.get_component(pkg, Component(name='x', suffix='xz'))
