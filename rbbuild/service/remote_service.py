# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import ssl

from abc import ABCMeta
from enum import Enum
from typing import Dict, Tuple

import requests

from requests.adapters import HTTPAdapter
from truststore import SSLContext as TruststoreContext

from rbbuild.librbb.term import term


class AuthMethod(Enum):
    NONE = 0
    BASIC = 1
    BEARER_TOKEN = 2
    OAUTH2 = 3


    # Reads 'auth-method' of a [profile.services.<name>] table; none if undefined.
    @classmethod
    def from_config(cls, service_config: dict, service_name: str) -> 'AuthMethod':
        value = service_config.get('auth-method', 'none')
        try:
            return cls[str(value).upper().replace('-', '_')]
        except KeyError:
            valid = ', '.join(m.name.lower().replace('_', '-') for m in cls)
            raise SyntaxError(
                f'[profile.services.{service_name}]: invalid auth-method "{value}" (valid: {valid})'
            ) from None


# Reads 'truststore' of a [profile.services.<name>] table; false if undefined.
def truststore_from_config(service_config: dict, service_name: str) -> bool:
    value = service_config.get('truststore', False)
    if not isinstance(value, bool):
        raise SyntaxError(
            f'[profile.services.{service_name}]: invalid truststore "{value}" (valid: true, false)'
        )
    return value


# requests verifies against the certifi bundle by default
class TruststoreAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self._ssl_context = TruststoreContext(ssl.PROTOCOL_TLS_CLIENT)
        super().__init__(*args, **kwargs)


    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert
        )
        if verify is True:
            pool_kwargs['ssl_context'] = self._ssl_context
        return host_params, pool_kwargs


# In our context, a RemoteService is always a REST service.
# This abstract class defines the interfaces that must be implemented
# by a remote service
class RemoteService(metaclass=ABCMeta):
    # Services that set up self.auth for AuthMethod.OAUTH2 themselves
    oauth2_supported = False


    def __init__(
        self,
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        self.url: str = url
        self.headers: Dict[str, str] = {}
        self.auth: Tuple[str, str] = None
        self.session = requests.Session()
        if truststore:
            self.session.mount('https://', TruststoreAdapter())

        auth_err_msg = f'{term.bright_white(self.__class__.__name__)}: missing auth credentials: '
        if url:
            auth_err_msg += term.cyan(url)

        if auth_method == AuthMethod.BEARER_TOKEN:
            if user:
                self.auth = (user, credentials)
                if not user and not credentials:
                    raise RuntimeError(auth_err_msg)
            else:
                self.headers = {'Authorization' : f'Bearer {credentials}'}
                if not credentials:
                    raise RuntimeError(auth_err_msg)
        elif auth_method == AuthMethod.BASIC:
            self.auth = (user, credentials)
            if not user and not credentials:
                raise RuntimeError(auth_err_msg)
        elif auth_method == AuthMethod.OAUTH2:
            if not self.oauth2_supported:
                raise TypeError(
                    f'{self.__class__.__name__} does not support auth-method oauth2'
                )
        elif auth_method == AuthMethod.NONE:
            pass
        else:
            raise TypeError(f'Invalid authentication method {auth_method}')

