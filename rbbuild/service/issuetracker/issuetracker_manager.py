#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from rbbuild.librbb.term import term

from rbbuild.service.remote_service import (
    RemoteService, AuthMethod, truststore_from_config,
)


@dataclass
class Issue:
    key: str
    summary: str
    status: str

    @property
    def status_colored(self) -> str:
        if self.status == 'Closed':
            return term.green(self.status)
        if self.status == 'Open':
            return term.red(self.status)
        return term.yellow(self.status)


    # Extract and normalize the Jira issue key embedded in a branch name.
    # Example: 'PROJECT-1234-some-description' -> 'PROJECT-1234'
    # Any character that is not alphanumeric, '-', or '_' is replaced with '_'.
    @staticmethod
    def branch_abbreviated(branch: str) -> str:
        if branch:
            branch = re.sub(r'(\w+-\d+).*$', r'\1', branch)
            branch_out = ''
            for c in branch:
                if c.isalnum() or c in '-_':
                    branch_out += c
                else:
                    branch_out += '_'
            return branch_out
        return None


@dataclass
class Release:
    name: str
    description: str
    release_date: str
    archived: bool
    released: bool


class OrderHint(Enum):
    KEY_ASC=0
    KEY_DESC=1


# abstract class implemented by IssueTracker instances (Jira, ...)
class IssueTracker(RemoteService, metaclass=ABCMeta):
    def __init__(
        self,
        key: str,    # project identifer
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


    @property
    @abstractmethod
    def api_endpoint_url(self) -> str:
        pass


    # TODO: For now these are mere dummies
    # The present interfaces are based on the initial Jira implementation
    @abstractmethod
    def get_issue(self, issue: str) -> dict:
        pass


    @abstractmethod
    def search(self, query: str, order_hint: OrderHint=None) -> Iterator[Issue]:
        pass


    @abstractmethod
    def release_versions(self) -> Iterator[Release]:
        pass


class IssueTrackerManager:
    def __init__(
        self,
        profile_config,
        user_config,   # user overrides and credentials
        **providers
    ):
        self._providers = providers
        self._profile_config = profile_config
        self._user_config = user_config if user_config else {}


    # Generic service retrieval by registered identifier
    # This identifier is configured in the profile configuration:
    #
    #    [profile.issuetracker.PROJECT]
    #    remote_service = 'jira_tracker'
    #
    # In this example, the tracker can be retrieved using "PROJECT" as identifier
    def service(self, key: str) -> IssueTracker:
        config = self._profile_config.get('issuetracker', {}).get(key)
        if not config:
            raise LookupError(f'Issue tracker {key} is not configured for the current profile!')

        trackerid = config.get('remote_service', '')
        service_config = self._profile_config.get('services', {}).get(trackerid)
        if not service_config:
            raise LookupError(f'Remote service {trackerid} is not configured for the current profile!')

        user = self._user_config.get(trackerid, {})
        return self._providers[service_config['type']](
            key = key,
            url = service_config['url'],
            auth_method = AuthMethod.from_config(service_config, trackerid),
            user = user.get('user'),
            credentials = user.get('credentials'),
            truststore = truststore_from_config(service_config, trackerid),
        )

