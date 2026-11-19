# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import requests
import truststore

from rbbuild.service.issuetracker.jira import Jira
from rbbuild.service.remote_service import (
    AuthMethod, TruststoreAdapter, truststore_from_config,
)


def _make_jira(auth_method, user=None, credentials='secret'):
    return Jira(
        key='TEST',
        url='https://example.com/',
        auth_method=auth_method,
        user=user,
        credentials=credentials,
        truststore=False,
    )


# BEARER_TOKEN with a username → self.auth = (user, credentials)
def test_bearer_token_with_user():
    jira = _make_jira(AuthMethod.BEARER_TOKEN, user='testuser')
    assert jira.auth == ('testuser', 'secret')
    assert 'Authorization' not in jira.headers


# BEARER_TOKEN without username → Authorization: Bearer header, no auth tuple
def test_bearer_token_without_user():
    jira = _make_jira(AuthMethod.BEARER_TOKEN, user=None)
    assert jira.auth is None
    assert jira.headers.get('Authorization') == 'Bearer secret'


# BASIC auth → self.auth = (user, credentials)
def test_basic_auth():
    jira = _make_jira(AuthMethod.BASIC, user='basicuser')
    assert jira.auth == ('basicuser', 'secret')
    assert 'Authorization' not in jira.headers


# NONE auth → no credentials, no auth header
def test_no_auth():
    jira = _make_jira(AuthMethod.NONE)
    assert jira.auth is None
    assert jira.headers == {}


# Invalid auth method → TypeError
def test_invalid_auth_method():
    with pytest.raises(TypeError):
        _make_jira(auth_method='not_an_auth_method')


# AuthMethod.from_config: 'auth-method' of a [profile.services.<name>] table
def test_from_config_undefined_is_none():
    assert AuthMethod.from_config({'type': 'jira'}, 'svc') == AuthMethod.NONE


@pytest.mark.parametrize('value, expected', [
    ('none',         AuthMethod.NONE),
    ('basic',        AuthMethod.BASIC),
    ('bearer-token', AuthMethod.BEARER_TOKEN),
    ('bearer_token', AuthMethod.BEARER_TOKEN),
    ('BEARER-TOKEN', AuthMethod.BEARER_TOKEN),
])
def test_from_config_values(value, expected):
    assert AuthMethod.from_config({'auth-method': value}, 'svc') == expected


def test_from_config_invalid_raises():
    with pytest.raises(SyntaxError, match=r'svc.*invalid auth-method "oauth".*bearer-token'):
        AuthMethod.from_config({'auth-method': 'oauth'}, 'svc')


# truststore_from_config: 'truststore' of a [profile.services.<name>] table
def test_truststore_from_config_undefined_is_false():
    assert truststore_from_config({'type': 'jira'}, 'svc') is False


@pytest.mark.parametrize('value', [True, False])
def test_truststore_from_config_values(value):
    assert truststore_from_config({'truststore': value}, 'svc') is value


@pytest.mark.parametrize('value', ['true', 1, 'system'])
def test_truststore_from_config_invalid_raises(value):
    with pytest.raises(SyntaxError, match=r'svc.*invalid truststore'):
        truststore_from_config({'truststore': value}, 'svc')


def _make_service(truststore):
    return Jira(
        key='TEST',
        url='https://example.com/',
        auth_method=AuthMethod.NONE,
        user=None,
        credentials=None,
        truststore=truststore,
    )


def _https_adapter(service):
    return service.session.get_adapter('https://example.com/')


def test_truststore_disabled_uses_default_adapter():
    service = _make_service(truststore=False)
    assert not isinstance(_https_adapter(service), TruststoreAdapter)


def test_truststore_enabled_mounts_adapter_for_https_only():
    service = _make_service(truststore=True)
    assert isinstance(_https_adapter(service), TruststoreAdapter)
    assert not isinstance(
        service.session.get_adapter('http://example.com/'), TruststoreAdapter
    )


def test_truststore_is_per_service():
    enabled = _make_service(truststore=True)
    disabled = _make_service(truststore=False)
    assert enabled.session is not disabled.session
    assert not isinstance(_https_adapter(disabled), TruststoreAdapter)


def _pool_attributes(verify):
    request = requests.Request('GET', 'https://example.com/').prepare()
    return TruststoreAdapter().build_connection_pool_key_attributes(
        request, verify
    )[1]


def test_truststore_adapter_sets_ssl_context_when_verifying():
    pool_kwargs = _pool_attributes(True)
    assert isinstance(pool_kwargs['ssl_context'], truststore.SSLContext)


@pytest.mark.parametrize('verify', [False, '/path/to/ca-bundle.pem'])
def test_truststore_adapter_keeps_explicit_verify_settings(verify):
    assert 'ssl_context' not in _pool_attributes(verify)
