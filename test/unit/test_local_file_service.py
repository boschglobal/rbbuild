# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch

from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.repository.local_file_storage import LocalFileService


def _make_service(url):
    return LocalFileService(
        channel=MagicMock(remote_service='svc', repository='repo', root_path='root'),
        url=url,
        user=None,
        credentials=None,
        auth_method=AuthMethod.NONE,
        cache=MagicMock(),
        manifest=MagicMock(),
        temp_folder=MagicMock(),
        op_mode=MagicMock(),
        truststore=False,
    )


def test_missing_service_path_warns(tmp_path):
    url = f'file:{(tmp_path / "missing").as_posix()}'
    with patch('rbbuild.service.repository.local_file_storage.term') as term:
        _make_service(url)
    term.warning.assert_called_once()
    assert url in term.warning.call_args.args[0]


def test_existing_service_path_does_not_warn(tmp_path):
    with patch('rbbuild.service.repository.local_file_storage.term') as term:
        _make_service(f'file:{tmp_path.as_posix()}')
    term.warning.assert_not_called()
