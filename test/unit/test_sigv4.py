# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import hashlib

from datetime import datetime, timezone

import pytest
import requests

from rbbuild.service.sigv4 import EMPTY_PAYLOAD_SHA256, SigV4Auth

# Unit tests for SigV4Auth. The signatures are the examples of the AWS S3
# documentation ("Signature Calculations for the Authorization Header").

_NOW = datetime(2013, 5, 24, tzinfo=timezone.utc)


def _auth():
    return SigV4Auth(
        'AKIAIOSFODNN7EXAMPLE',
        'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        'us-east-1',
    )


def _sign(method, url, **kwargs):
    req = requests.Request(method, url, **kwargs).prepare()
    return _auth()(req, now=_NOW)


# GET Object with a Range header
def test_get_object_signature():
    req = _sign(
        'GET',
        'https://examplebucket.s3.amazonaws.com/test.txt',
        headers={'Range': 'bytes=0-9'},
    )

    assert req.headers['Authorization'] == (
        'AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, '
        'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, '
        'Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'
    )
    assert req.headers['x-amz-content-sha256'] == EMPTY_PAYLOAD_SHA256


# Sub-resource query without a value
def test_query_without_value_signature():
    req = _sign('GET', 'https://examplebucket.s3.amazonaws.com/?lifecycle')

    assert req.headers['Authorization'].endswith(
        'Signature=fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543'
    )


# PUT with a request body: the body is hashed and x-amz-* headers are signed
def test_put_hashes_body_and_signs_amz_headers():
    req = _sign(
        'PUT',
        'https://examplebucket.s3.amazonaws.com/test$file.text',
        data=b'Welcome to Amazon S3.',
        headers={'x-amz-storage-class': 'REDUCED_REDUNDANCY'},
    )

    assert req.headers['x-amz-content-sha256'] == hashlib.sha256(b'Welcome to Amazon S3.').hexdigest()
    assert 'SignedHeaders=host;x-amz-content-sha256;x-amz-date;x-amz-storage-class' in req.headers['Authorization']


# A preset payload hash is used as-is, which is required for streamed bodies
def test_preset_payload_hash_is_kept():
    req = requests.Request(
        'PUT',
        'https://s3.test/bkt/key',
        headers={'x-amz-content-sha256': 'abc'},
    ).prepare()

    _auth()(req, now=_NOW)

    assert req.headers['x-amz-content-sha256'] == 'abc'


def test_streamed_body_without_payload_hash_raises():
    req = requests.Request('PUT', 'https://s3.test/bkt/key').prepare()
    req.body = iter([b'data'])

    with pytest.raises(ValueError, match='x-amz-content-sha256'):
        _auth()(req, now=_NOW)
