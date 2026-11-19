# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re

from urllib.parse import urlparse

from rbbuild.service.remote_service import AuthMethod, truststore_from_config

from .git_repository import GitRepository


class SCMManager:
    def __init__(
        self,
        services_config: dict,
        user_config: dict,
        **providers,
    ):
        self._providers = providers
        self._services_config = services_config
        self._user_config = user_config if user_config else {}


    # Return Git repository service by URL string
    def service(
        self,
        *,
        url: str=None,             # Variant 1: reverse search service, extract project and repo
        remote_service: str=None,  # Variant 2: search service by service name
        project: str=None,         # needed for variant 2
        repository: str=None,      # needed for variant 2
    ) -> GitRepository:
        if url:
            for service_name, service_config in self._services_config.items():
                if self._compare_url(url, service_config.get('url')):
                    remote_service = service_name
                    break

            # Expected Git URL variants:
            #   - https://git.service/scm/<PROJECT>/<REPO>.git
            #   - ssh://git@git.service:7999/<PROJECT>/<REPO>.git
            #   - https://github.com/<PROJECT>/<REPO>.git
            #   - git@github.com:<PROJECT>/<REPO>.git
            #
            m = (re.match(r'git@[\w.-]+:([\w-]+)/([\w-]+)\.git$', url)
                 or re.match(r'.*/([\w-]+)/([\w-]+)\.git$', urlparse(url).path))
            if not m:
                raise SyntaxError(f'Invalid git URL {url}')
            project = m[1]
            repository = m[2]

        if not remote_service or not project or not repository:
            raise RuntimeError('Invalid arguments. remote service, project, and repository must be set')

        config = self._services_config.get(remote_service, {})
        user = self._user_config.get(remote_service, {})
        if not config:
            raise LookupError(f'SCM remote service for {url!s} is not configured for the current profile!')

        return self._providers[config['type']](
            endpoint_url = config['url'],
            project      = project,
            repository   = repository,
            auth_method  = AuthMethod.from_config(config, remote_service),
            user         = user.get('user'),
            credentials  = user.get('credentials'),
            truststore   = truststore_from_config(config, remote_service),
        )


    def _compare_url(self, url: str, remote_config_url: str) -> bool:
        # URL from remote service configuration, e.g:
        # - https://git.service/
        # - https://api.github.com/
        p_url_remote = urlparse(remote_config_url)

        # SSH-style URLs (urlparse cannot parse them)
        # - ssh://git@git.service:7999/<PROJECT>/<REPO>.git
        m = re.match(r'git@([\w.-]+):', url)
        if m:
            return m.group(1) in (p_url_remote.hostname or '')

        p_url = urlparse(url)

        # HTTP case expected input:
        # - https://git.service/scm/<PROJECT>/<REPO>.git
        # We can compare the hostnames and then match project/repo.git
        if p_url.hostname == p_url_remote.hostname:
            return True

        # GitHub case expected input:
        # - https://github.com/<PROJECT>/<REPO>.git
        if p_url.hostname == 'github.com' and p_url_remote.hostname == 'api.github.com':
            return True

        return False

