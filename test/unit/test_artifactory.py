# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch

import pytest
import requests

from rbbuild.package.component import Component
from rbbuild.service.repository.artifactory import Artifactory
from rbbuild.service.repository.repository import VersionConflictError

# Unit tests for Artifactory.upload_component() version-conflict detection.
# A minimal instance is built via MagicMock(spec=...) with the real method
# bound, following the pattern used in test_repository.py.


def _make_artifactory(force=False, dry_run=False):
    repo = MagicMock(spec=Artifactory)
    repo.op_mode = MagicMock(force=force, dry_run=dry_run)
    repo.channel = MagicMock(repository='myrepo', root_path='', name='development')
    repo.headers = {}
    repo.auth = None
    repo.session = MagicMock()
    repo.url = 'https://example.test/'
    repo.tmpdir = None
    repo.progress_cb = None
    repo.upload_component = Artifactory.upload_component.__get__(repo, Artifactory)
    return repo


def _make_component(tmp_path, filename='pkg-1.0.tar', checksum='abc'):
    localpath = tmp_path / filename
    localpath.write_bytes(b'data')
    return Component(name='pkg', suffix='tar', filename=filename, localpath=localpath, checksum=checksum)


# Any component that already exists remotely is a version conflict, even
# without --force.
def test_component_already_exists_raises_conflict(tmp_path):
    repo = _make_artifactory(force=False)
    repo.exists.return_value = True
    comp = _make_component(tmp_path)

    with pytest.raises(VersionConflictError):
        repo.upload_component(name='pkg', version='1.0', component=comp)


# Same as above, but with --force: a conflict must still be raised, not
# silently overwritten.
def test_component_already_exists_raises_conflict_even_with_force(tmp_path):
    repo = _make_artifactory(force=True)
    repo.exists.return_value = True
    comp = _make_component(tmp_path)

    with pytest.raises(VersionConflictError):
        repo.upload_component(name='pkg', version='1.0', component=comp)


# HTTP 409 while actually uploading (e.g. a race with another publisher) is
# reported as a conflict.
@pytest.mark.parametrize('status_code', [403, 409])
def test_http_conflict_status_raises_conflict(tmp_path, status_code):
    repo = _make_artifactory(force=True)
    repo.exists.return_value = False
    comp = _make_component(tmp_path)

    fake_response = MagicMock(status_code=status_code)
    http_error = requests.exceptions.HTTPError(response=fake_response)

    with patch('rbbuild.service.repository.artifactory.RESTHelper') as mock_helper_cls:
        mock_helper_cls.return_value.upload_file.side_effect = http_error
        with pytest.raises(VersionConflictError):
            repo.upload_component(name='pkg', version='1.0', component=comp)


# A non-conflict HTTP error (e.g. 500) propagates unchanged.
def test_other_http_error_propagates(tmp_path):
    repo = _make_artifactory(force=True)
    repo.exists.return_value = False
    comp = _make_component(tmp_path)

    fake_response = MagicMock(status_code=500)
    http_error = requests.exceptions.HTTPError(response=fake_response)

    with patch('rbbuild.service.repository.artifactory.RESTHelper') as mock_helper_cls:
        mock_helper_cls.return_value.upload_file.side_effect = http_error
        with pytest.raises(requests.exceptions.HTTPError):
            repo.upload_component(name='pkg', version='1.0', component=comp)


# dry-run never touches exists()/upload.
def test_dry_run_skips_without_conflict_check(tmp_path):
    repo = _make_artifactory(dry_run=True)
    comp = _make_component(tmp_path)

    result = repo.upload_component(name='pkg', version='1.0', component=comp)

    assert result is True
    repo.exists.assert_not_called()
