# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import requests

from rbbuild.service.oauth2 import OAuth2RefreshAuth

_TOKEN_URL = 'https://oauth2.example.test/token'


def _auth(session=None):
    return OAuth2RefreshAuth(
        session or requests.Session(), _TOKEN_URL, 'cid', 'csecret', 'rtoken'
    )


def _prepared():
    return requests.Request('GET', 'https://api.example.test/x').prepare()


def test_sends_bearer_token_from_refresh_token(requests_mock):
    token = requests_mock.post(
        _TOKEN_URL, json={'access_token': 'tok', 'expires_in': 3600})

    req = _auth()(_prepared())

    assert req.headers['Authorization'] == 'Bearer tok'
    assert token.last_request.text == (
        'grant_type=refresh_token&client_id=cid'
        '&client_secret=csecret&refresh_token=rtoken'
    )


def test_token_is_reused_until_expiry(requests_mock):
    token = requests_mock.post(
        _TOKEN_URL, json={'access_token': 'tok', 'expires_in': 3600})
    auth = _auth()

    auth(_prepared())
    auth(_prepared())

    assert token.call_count == 1


# The token is refreshed shortly before it expires.
def test_token_is_refreshed_when_expired(requests_mock):
    token = requests_mock.post(
        _TOKEN_URL, json={'access_token': 'tok', 'expires_in': 30})
    auth = _auth()

    auth(_prepared())
    auth(_prepared())

    assert token.call_count == 2


def test_refresh_failure_reports_reason(requests_mock):
    requests_mock.post(
        _TOKEN_URL,
        status_code=400,
        json={'error': 'invalid_grant', 'error_description': 'Token has been revoked'},
    )

    with pytest.raises(RuntimeError, match='HTTP 400.*Token has been revoked'):
        _auth()(_prepared())


def test_refresh_failure_without_json_body(requests_mock):
    requests_mock.post(_TOKEN_URL, status_code=502, text='bad gateway')

    with pytest.raises(RuntimeError, match='HTTP 502'):
        _auth()(_prepared())
