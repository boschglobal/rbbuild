# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock

import pytest

from rbbuild.service.ci.manager import CIManager
from rbbuild.service.issuetracker.issuetracker_manager import IssueTrackerManager
from rbbuild.service.oss.oss_manager import OSSManager
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.scm.manager import SCMManager


# Each manager must pass the 'auth-method' of the remote service's profile
# configuration as auth_method to the service provider (none if undefined).

def _service_config(**extra):
    return {'type': 'mytype', 'url': 'https://example.com/', **extra}


def _ci(service_config):
    provider = MagicMock()
    manager = CIManager(
        profile_config={'ci': {'K': {'remote_service': 'svc'}}, 'services': {'svc': service_config}},
        user_config={},
        mytype=provider,
    )
    manager.service('K')
    return provider


def _issuetracker(service_config):
    provider = MagicMock()
    manager = IssueTrackerManager(
        profile_config={'issuetracker': {'K': {'remote_service': 'svc'}}, 'services': {'svc': service_config}},
        user_config={},
        mytype=provider,
    )
    manager.service('K')
    return provider


def _oss(service_config):
    provider = MagicMock()
    manager = OSSManager(
        profile_config={
            'oss': {'K': {'type': 'mytype', 'remote_service': 'svc'}},
            'services': {'svc': service_config},
        },
        user_config={},
        oss_config={},
        mytype=provider,
    )
    manager.service('K')
    return provider


def _scm(service_config):
    provider = MagicMock()
    manager = SCMManager(
        services_config={'svc': service_config},
        user_config={},
        mytype=provider,
    )
    manager.service(remote_service='svc', project='proj', repository='repo')
    return provider


_FACTORIES = [_ci, _issuetracker, _oss, _scm]


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_auth_method_undefined_is_none(factory):
    provider = factory(_service_config())
    assert provider.call_args.kwargs['auth_method'] == AuthMethod.NONE


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_auth_method_from_config(factory):
    provider = factory(_service_config(**{'auth-method': 'bearer-token'}))
    assert provider.call_args.kwargs['auth_method'] == AuthMethod.BEARER_TOKEN


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_auth_method_invalid_raises(factory):
    with pytest.raises(SyntaxError, match='invalid auth-method'):
        factory(_service_config(**{'auth-method': 'oauth'}))


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_truststore_undefined_is_false(factory):
    provider = factory(_service_config())
    assert provider.call_args.kwargs['truststore'] is False


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_truststore_from_config(factory):
    provider = factory(_service_config(truststore=True))
    assert provider.call_args.kwargs['truststore'] is True


@pytest.mark.parametrize('factory', _FACTORIES)
def test_manager_truststore_invalid_raises(factory):
    with pytest.raises(SyntaxError, match='invalid truststore'):
        factory(_service_config(truststore='yes'))


def test_ci_manager_without_user_config():
    provider = MagicMock()
    manager = CIManager(
        profile_config={'ci': {'K': {'remote_service': 'svc'}}, 'services': {'svc': _service_config()}},
        user_config=None,
        mytype=provider,
    )
    manager.service('K')
    assert provider.call_args.kwargs['user'] is None


def test_issuetracker_manager_without_user_config():
    provider = MagicMock()
    manager = IssueTrackerManager(
        profile_config={'issuetracker': {'K': {'remote_service': 'svc'}}, 'services': {'svc': _service_config()}},
        user_config=None,
        mytype=provider,
    )
    manager.service('K')
    assert provider.call_args.kwargs['user'] is None
