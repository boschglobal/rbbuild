# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from rbbuild.service.oss.fossid import FossID
from rbbuild.service.remote_service import AuthMethod, truststore_from_config


# Facade for Open Source Scanner (OSS) services (e.g., FossID).
#
# Profile configuration:
#
#     [profile.oss.PROJECT]
#     type               = 'fossid'
#     project_org_prefix = 'ORG_PROJECT'
#     remote_service     = 'fossid_service'
#     users              = ['jdoe']
#     ignore_files       = ['.gitignore', 'Jenkinsfile']
#     ignore_folders     = ['.git']
#
# The 'type' field maps to a provider registered in OSSContainer
# (currently only 'fossid' is supported).
class OSSManager:

    def __init__(
        self,
        profile_config,
        user_config,   # user overrides and credentials
        oss_config,
        **providers
    ):
        self._providers = providers
        self._profile_config = profile_config
        self._user_config = user_config if user_config else {}
        self._oss_config = oss_config if oss_config else {}


    # Return an OSS service instance for the given profile entry name.
    def service(self, name: str) -> FossID:
        config = self._profile_config.get('oss', {}).get(name)
        if not config:
            raise LookupError(f'OSS entry "{name}" is not configured for the current profile!')

        service_type = config.get('type')
        if not service_type:
            raise SyntaxError(f'Profile configuration error [profile.oss.{name}]: type must be defined!')
        if service_type not in self._providers:
            raise LookupError(f'OSS service type "{service_type}" is not supported!')

        service_id = config.get('remote_service', '')
        service_config = self._profile_config.get('services', {}).get(service_id)
        if not service_config:
            raise LookupError(f'Remote service "{service_id}" is not configured for the current profile!')

        user = self._user_config.get(service_id, {})
        return self._providers[service_type](
            name=name,
            url=service_config['url'],
            auth_method=AuthMethod.from_config(service_config, service_id),
            user=user.get('user'),
            credentials=user.get('credentials'),
            truststore=truststore_from_config(service_config, service_id),
            project_org_prefix=config.get('project_org_prefix', ''),
        )


    # Combined OSS config from profile settings (section [profile.oss.<name>])
    # and project config (rbbuild.toml or pyproject.toml: [oss] section)
    def oss_config(self, name: str) -> dict:
        cfg = self._profile_config.get('oss', {}).get(name, {})
        # overwrite profile configuration with settings from project settings
        # (rbbuild.toml), if any
        if self._oss_config:
            cfg = cfg.copy()
            cfg.update(self._oss_config)
        return cfg


    # Return all OSS entry names defined in the profile.
    def names(self):
        return self._profile_config.get('oss', {}).keys()
