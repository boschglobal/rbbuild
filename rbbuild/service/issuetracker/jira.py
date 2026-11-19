#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from urllib.parse import quote_plus
from typing import Iterator

from rbbuild.service.remote_service import AuthMethod

from .issuetracker_manager import IssueTracker, Release, Issue, OrderHint


class Jira(IssueTracker):
    def __init__(
        self,
        key: str,   # Jira project identifier
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        IssueTracker.__init__(
            self,
            key=key,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )


    def make_order_hint(self, order_hint: OrderHint):
        if order_hint == OrderHint.KEY_ASC:
            return 'ORDER BY key ASC'
        if order_hint == OrderHint.KEY_DESC:
            return 'ORDER BY key DESC'
        return ''


    @property
    def api_endpoint_url(self) -> str:
        return f'{self.url}rest/api/2/'


    def get_issue(self, issue: str) -> dict:
        if '-' not in issue:
            raise SyntaxError(f'Invalid ticket form "{issue}". Expected "<jira-key>-<ticket-id>".')

        url = f'{self.api_endpoint_url}issue/{issue}?fields=issuelinks'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        resp = self.session.get(url=url, headers=headers, auth=self.auth)

        if resp.ok:
            return resp.json()
        return {}


    def search(self, query: str, order_hint: OrderHint=None) -> Iterator[Issue]:
        # Automatically prepend project= if not present
        jql = ''
        if 'project' not in query.lower():
            jql += f'project={self.key} AND'

        jql += f' {query}'

        if 'order by' not in query.lower():
            jql += f' {self.make_order_hint(order_hint)}'

        jql_safe = quote_plus(jql)  # convert to safe URL params
        url = f'{self.api_endpoint_url}search?jql={jql_safe}'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        resp = self.session.get(url=url, headers=headers, auth=self.auth)
        if not resp.ok:
            error_messages = '\t\n'.join(resp.json().get('errorMessages', []))
            raise RuntimeError(f'GET {url} failed:\t\n{error_messages}')

        for data in resp.json().get('issues', {}):
            yield Issue(
                key=data.get('key', ''),
                summary=data.get('fields', {}).get('summary', ''),
                status=data.get('fields', {}).get('status', {}).get('name', ''),
            )


    def release_versions(self) -> Iterator[Release]:
        url = f'{self.api_endpoint_url}project/{self.key}/versions'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        resp = self.session.get(url=url, headers=headers, auth=self.auth)
        for data in resp.json():
            yield Release(
                name=data.get('name', ''),
                description=data.get('description', ''),
                release_date=data.get('releaseDate', ''),
                archived=data.get('archived', False),
                released=data.get('released', False),
            )

