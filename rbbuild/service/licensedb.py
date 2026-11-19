#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import functools

from .remote_service import RemoteService, AuthMethod, truststore_from_config


class LicenseDB(RemoteService):
    def __init__(
        self,
        licensedb_config: dict,
        remote_services_config: dict,
        profile_name: str,
    ):
        if not licensedb_config or profile_name not in licensedb_config:
            raise LookupError(f'LicenseDB not configured for profile {profile_name} ([profile.licensedb.{profile_name}])')

        remote_service_name = licensedb_config[profile_name].get('remote_service')
        if not remote_service_name or remote_service_name not in remote_services_config:
            raise LookupError(f'Remote service for [profile.licensedb.{profile_name} not found!')
        remote_service = remote_services_config[remote_service_name]

        RemoteService.__init__(
            self,
            url=remote_service['url'],
            auth_method=AuthMethod.NONE,
            user=None,
            credentials=None,
            truststore=truststore_from_config(
                remote_service, remote_service_name
            ),
        )


    @functools.cached_property
    def _all_licenses(self) -> dict:
         url = f'{self.url}api/v2/licenses'
         resp = self.session.get(url, headers=self.headers)
         resp.raise_for_status()
         return resp.json()


    def is_registered(self, spdx_identifier: str) -> bool:
        for entry in self._all_licenses:
            if entry.get('spdx_short_identifier') == spdx_identifier:
                return True

        return False


    def is_permissive(self, spdx_identifier: str) -> bool:
        for entry in self._all_licenses:
            if entry.get('spdx_short_identifier') == spdx_identifier:
                if entry.get('category').lower() == 'permissive':
                    return True
        return False

