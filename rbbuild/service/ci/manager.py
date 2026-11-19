#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from abc import ABCMeta, abstractmethod
from typing import Optional

from rbbuild.service.remote_service import (
    RemoteService, AuthMethod, truststore_from_config,
)


# Abstract class implemented by CI system instances (Jenkins, GitHub Actions, ...).
class CIService(RemoteService, metaclass=ABCMeta):
    def __init__(
        self,
        key: str,    # profile/project identifier
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        RemoteService.__init__(
            self,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.key = key



    @abstractmethod
    def job_url(self) -> Optional[str]:
        pass


# https://refactoring.guru/design-patterns/facade
class CIManager:
    def __init__(
        self,
        profile_config,
        user_config,   # user overrides and credentials
        **providers
    ):
        self._providers = providers
        self._profile_config = profile_config
        self._user_config = user_config if user_config else {}


    # Generic service retrieval by registered identifier. This identifier is
    # configured in the profile configuration:
    #
    #    [profile.ci.PROJECT]
    #    remote_service = 'ci_service'
    #
    # In this example, the CI system can be retrieved using "PROJECT" as identifier.
    def service(self, key: str) -> CIService:
        config = self._profile_config.get('ci', {}).get(key)
        if not config:
            raise LookupError(f'CI system {key} is not configured for the current profile!')

        serviceid = config.get('remote_service', '')
        service_config = self._profile_config.get('services', {}).get(serviceid)
        if not service_config:
            raise LookupError(f'Remote service {serviceid} is not configured for the current profile!')

        user = self._user_config.get(serviceid, {})
        return self._providers[service_config['type']](
            key=key,
            url=service_config['url'],
            auth_method=AuthMethod.from_config(service_config, serviceid),
            user=user.get('user'),
            credentials=user.get('credentials'),
            truststore=truststore_from_config(service_config, serviceid),
        )
