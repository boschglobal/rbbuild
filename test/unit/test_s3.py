# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import hashlib
import json

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from rbbuild.package.component import Component
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.repository.repository import VersionConflictError
from rbbuild.service.repository.s3 import S3

# Unit tests for the S3 repository against a mocked HTTP endpoint.

_BASE = 'https://s3.example.test'
_NS = 'http://s3.amazonaws.com/doc/2006-03-01/'


def _make_s3(tmp_path, chtype='rbbuild', root_path='root', options=None,
             force=False, dry_run=False, url=f'{_BASE}/',
             user='AKID', credentials='SECRET'):
    channel = MagicMock(
        remote_service='svc', repository='bkt', root_path=root_path, type=chtype)
    channel.name = 'development'
    manifest = MagicMock()
    manifest.make_filename.side_effect = (
        lambda name, version, toolchain, legacy=False:
        f'{name}-{version}{"-legacy" if legacy else ""}-manifest.json')
    return S3(
        channel=channel,
        cache=MagicMock(),
        manifest=manifest,
        temp_folder=MagicMock(path=tmp_path),
        url=url,
        auth_method=AuthMethod.NONE,
        user=user,
        credentials=credentials,
        op_mode=MagicMock(force=force, dry_run=dry_run),
        truststore=False,
        options=options,
    )


def _listing(keys=(), prefixes=(), token=None):
    body = f'<ListBucketResult xmlns="{_NS}">'
    body += f'<IsTruncated>{"true" if token else "false"}</IsTruncated>'
    if token:
        body += f'<NextContinuationToken>{token}</NextContinuationToken>'
    body += ''.join(f'<Contents><Key>{k}</Key></Contents>' for k in keys)
    body += ''.join(
        f'<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>' for p in prefixes)
    return body + '</ListBucketResult>'


def _component(tmp_path, filename='pkg-1.0.tar', data=b'data'):
    localpath = tmp_path / filename
    localpath.write_bytes(data)
    return Component(name='pkg', suffix='tar', filename=filename, localpath=localpath)


def test_url_is_required(tmp_path):
    with pytest.raises(SyntaxError, match='svc.*url is required'):
        _make_s3(tmp_path, url=None)


@pytest.mark.parametrize('user, credentials', [(None, 'secret'), ('akid', None)])
def test_credentials_are_required(tmp_path, user, credentials):
    channel = MagicMock(remote_service='svc')

    with pytest.raises(RuntimeError, match='missing access key'):
        S3(channel=channel, cache=None, manifest=None, temp_folder=None,
           url=_BASE, auth_method=AuthMethod.NONE, user=user,
           credentials=credentials, op_mode=None, truststore=False)


def test_requests_are_signed_with_default_region(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing())

    _make_s3(tmp_path).get_versions('pkg')

    auth = requests_mock.last_request.headers['Authorization']
    assert auth.startswith('AWS4-HMAC-SHA256 Credential=AKID/')
    assert '/us-east-1/s3/aws4_request' in auth


def test_region_option_is_used_for_signing(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing())

    _make_s3(tmp_path, options={'region': 'eu-central-1'}).get_versions('pkg')

    assert '/eu-central-1/s3/aws4_request' in requests_mock.last_request.headers['Authorization']


def test_get_versions(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt',
        text=_listing(prefixes=['root/pkg/1.0/', 'root/pkg/2.0/']),
    )

    assert _make_s3(tmp_path).get_versions('pkg') == ['1.0', '2.0']
    assert requests_mock.last_request.qs['prefix'] == ['root/pkg/']
    assert requests_mock.last_request.qs['delimiter'] == ['/']


def test_listing_follows_continuation_token(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', [
        {'text': _listing(prefixes=['root/pkg/1.0/'], token='next')},
        {'text': _listing(prefixes=['root/pkg/2.0/'])},
    ])

    assert _make_s3(tmp_path).get_versions('pkg') == ['1.0', '2.0']
    assert requests_mock.last_request.qs['continuation-token'] == ['next']


def test_url_without_namespace_is_parsed(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt',
        text='<ListBucketResult><IsTruncated>false</IsTruncated>'
             '<CommonPrefixes><Prefix>root/pkg/1.0/</Prefix></CommonPrefixes>'
             '</ListBucketResult>',
    )

    assert _make_s3(tmp_path).get_versions('pkg') == ['1.0']


def test_list_package_names_filters_by_pattern(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt',
        text=_listing(prefixes=['root/boost/', 'root/zlib/']),
    )

    assert list(_make_s3(tmp_path).list_package_names('b*')) == ['boost']
    assert list(_make_s3(tmp_path).list_package_names(None)) == ['boost', 'zlib']


def test_list_package_names_without_root_path(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing(prefixes=['boost/']))

    assert list(_make_s3(tmp_path, root_path='').list_package_names(None)) == ['boost']
    assert requests_mock.last_request.qs['prefix'] == ['']


def test_list_manifest_names(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing(keys=[
        'root/pkg/1.0/pkg-1.0-linux-manifest.json',
        'root/pkg/1.0/pkg-1.0.tar',
        'root/pkg/1.0/sub/other-manifest.json',
    ]))

    assert _make_s3(tmp_path).list_manifest_names('pkg', '1.0') == [
        'pkg-1.0-linux-manifest.json']


def test_get_package_downloads_manifest(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0-manifest.json', content=b'{}')
    pkg = Package(name='pkg', version='1.0')

    path = _make_s3(tmp_path).get_package(pkg)

    assert path.read_bytes() == b'{}'


def test_get_package_falls_back_to_legacy_manifest(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0-manifest.json', status_code=404)
    requests_mock.get(
        f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0-legacy-manifest.json', content=b'{}')

    path = _make_s3(tmp_path).get_package(Package(name='pkg', version='1.0'))

    assert path.name == 'pkg-1.0-legacy-manifest.json'


def test_get_package_missing_raises_lookup_error(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0-manifest.json', status_code=404)
    requests_mock.get(
        f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0-legacy-manifest.json', status_code=404)

    with pytest.raises(LookupError, match='pkg-1.0'):
        _make_s3(tmp_path).get_package(Package(name='pkg', version='1.0'))


def test_get_package_of_plain_channel_lists_files(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt', text=_listing(keys=['root/pkg/1.0/pkg-1.0.tar.gz']))

    path = _make_s3(tmp_path, chtype='plain').get_package(
        Package(name='pkg', version='1.0'))

    components = json.loads(path.read_text())['package']['components']
    assert [c['filename'] for c in components] == ['pkg-1.0.tar.gz']
    assert components[0]['suffix'] == 'gz'


def test_get_package_of_unknown_channel_type_raises(tmp_path):
    with pytest.raises(RuntimeError, match='Unknown S3 channel type pypi'):
        _make_s3(tmp_path, chtype='pypi').get_package(Package(name='pkg', version='1.0'))


def test_get_component_downloads_file(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar', content=b'data')
    comp = Component(name='pkg', suffix='tar', filename='pkg-1.0.tar')

    path = _make_s3(tmp_path).get_component(Package(name='pkg', version='1.0'), comp)

    assert path.read_bytes() == b'data'


def test_error_response_reports_s3_code(tmp_path, requests_mock):
    requests_mock.get(
        f'{_BASE}/bkt',
        status_code=400,
        text='<Error><Code>AuthorizationHeaderMalformed</Code>'
             "<Message>the region 'us-east-1' is wrong; expecting 'eu-central-1'"
             '</Message></Error>',
    )

    with pytest.raises(requests.exceptions.HTTPError, match="AuthorizationHeaderMalformed.*expecting 'eu-central-1'"):
        _make_s3(tmp_path).get_versions('pkg')


def test_upload_puts_file_with_content_length_and_hash(tmp_path, requests_mock):
    url = f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(url, status_code=404)
    put = requests_mock.put(url)

    _make_s3(tmp_path).upload_component('pkg', '1.0', _component(tmp_path))

    headers = put.last_request.headers
    assert headers['Content-Length'] == '4'
    assert 'Transfer-Encoding' not in headers
    assert headers['x-amz-content-sha256'] == hashlib.sha256(b'data').hexdigest()
    assert 'Authorization' in headers


def test_upload_of_empty_file_has_content_length(tmp_path, requests_mock):
    url = f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(url, status_code=404)
    put = requests_mock.put(url)

    _make_s3(tmp_path).upload_component('pkg', '1.0', _component(tmp_path, data=b''))

    assert put.last_request.headers['Content-Length'] == '0'
    assert 'Transfer-Encoding' not in put.last_request.headers


def test_upload_of_existing_object_raises_conflict(tmp_path, requests_mock):
    url = f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(url)
    put = requests_mock.put(url)

    with pytest.raises(VersionConflictError):
        _make_s3(tmp_path, force=True).upload_component(
            'pkg', '1.0', _component(tmp_path))

    assert not put.called


@pytest.mark.parametrize('status_code', [409, 412])
def test_upload_conflict_status_raises_conflict(tmp_path, requests_mock, status_code):
    url = f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(url, status_code=404)
    requests_mock.put(url, status_code=status_code)

    with pytest.raises(VersionConflictError):
        _make_s3(tmp_path).upload_component('pkg', '1.0', _component(tmp_path))


def test_upload_other_error_propagates(tmp_path, requests_mock):
    url = f'{_BASE}/bkt/root/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(url, status_code=404)
    requests_mock.put(url, status_code=403, text='<Error><Code>AccessDenied</Code></Error>')

    with pytest.raises(requests.exceptions.HTTPError, match='AccessDenied'):
        _make_s3(tmp_path).upload_component('pkg', '1.0', _component(tmp_path))


def test_upload_dry_run_sends_nothing(tmp_path, requests_mock):
    result = _make_s3(tmp_path, dry_run=True).upload_component(
        'pkg', '1.0', _component(tmp_path))

    assert result is True
    assert requests_mock.call_count == 0


def _channel(repository, root_path):
    return MagicMock(repository=repository, root_path=root_path)


def _copy(s3, **kwargs):
    return s3.copy(
        localfile=Path('pkg-1.0.tar'), name='pkg', version='1.0',
        source_channel=_channel('src', 'root'),
        destination_channel=_channel('dst', 'prod'),
        sha1sum=None, **kwargs)


def test_copy_uses_server_side_copy(tmp_path, requests_mock):
    dest = f'{_BASE}/dst/prod/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(dest, status_code=404)
    put = requests_mock.put(dest, text='<CopyObjectResult/>')

    assert _copy(_make_s3(tmp_path)) is True
    assert put.last_request.headers['x-amz-copy-source'] == 'src/root/pkg/1.0/pkg-1.0.tar'


def test_copy_skips_existing_destination(tmp_path, requests_mock):
    dest = f'{_BASE}/dst/prod/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(dest)
    put = requests_mock.put(dest)

    assert _copy(_make_s3(tmp_path)) is False
    assert not put.called


def test_copy_with_force_overwrites_without_checking(tmp_path, requests_mock):
    dest = f'{_BASE}/dst/prod/pkg/1.0/pkg-1.0.tar'
    put = requests_mock.put(dest, text='<CopyObjectResult/>')

    assert _copy(_make_s3(tmp_path, force=True)) is True
    assert put.called


def test_copy_dry_run_sends_no_copy(tmp_path, requests_mock):
    dest = f'{_BASE}/dst/prod/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(dest, status_code=404)
    put = requests_mock.put(dest)

    assert _copy(_make_s3(tmp_path, dry_run=True)) is True
    assert not put.called


def test_copy_error_in_ok_response_raises(tmp_path, requests_mock):
    dest = f'{_BASE}/dst/prod/pkg/1.0/pkg-1.0.tar'
    requests_mock.head(dest, status_code=404)
    requests_mock.put(dest, text='<Error><Code>InternalError</Code></Error>')

    with pytest.raises(RuntimeError, match='InternalError'):
        _copy(_make_s3(tmp_path))


def test_delete_removes_all_objects_of_version(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing(keys=[
        'root/pkg/1.0/a.tar', 'root/pkg/1.0/a-manifest.json']))
    delete_a = requests_mock.delete(f'{_BASE}/bkt/root/pkg/1.0/a.tar')
    delete_m = requests_mock.delete(f'{_BASE}/bkt/root/pkg/1.0/a-manifest.json')

    assert _make_s3(tmp_path).delete('pkg', '1.0') is True
    assert delete_a.called and delete_m.called


def test_delete_of_missing_version_returns_false(tmp_path, requests_mock):
    requests_mock.get(f'{_BASE}/bkt', text=_listing())

    assert _make_s3(tmp_path).delete('pkg', '1.0') is False


def test_resource_url(tmp_path):
    pkg = Package(name='pkg', version='1.0')

    assert _make_s3(tmp_path).resource_url(pkg) == f'{_BASE}/bkt/root/pkg/1.0'


def test_url_with_trailing_slash_and_path_prefix(tmp_path):
    s3 = _make_s3(tmp_path, url='https://minio.example.test:9000/s3/')

    assert s3.resource_url(Package(name='pkg', version='1.0')) == (
        'https://minio.example.test:9000/s3/bkt/root/pkg/1.0')


# Server-side copy is signed with the credentials of the source service
def test_can_copy_to_service_with_same_account_and_region(tmp_path):
    assert _make_s3(tmp_path).can_copy_to(_make_s3(tmp_path)) is True


@pytest.mark.parametrize('kwargs', [
    {'user': 'OTHER'},
    {'credentials': 'OTHER'},
    {'options': {'region': 'eu-central-1'}},
    {'url': 'https://other.example.test/'},
])
def test_cannot_copy_to_service_with_different_settings(tmp_path, kwargs):
    assert _make_s3(tmp_path).can_copy_to(_make_s3(tmp_path, **kwargs)) is False
