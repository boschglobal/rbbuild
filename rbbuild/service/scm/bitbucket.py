#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from typing import Iterator

from rbbuild.service.remote_service import AuthMethod

from .git_repository import GitRepository, GitCommit


class Bitbucket(GitRepository):
    def __init__(
        self,
        endpoint_url: str,
        project: str,
        repository: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        GitRepository.__init__(
            self,
            url=endpoint_url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.project = project
        self.repository = repository


    def get_commits(self, since: str=None, until: str=None, limit: int=100) -> Iterator[GitCommit]:
        url = f'{self.url}rest/api/1.0/projects/{self.project}/repos/{self.repository}/commits?limit={limit}&merges=include'
        if since:
            url += f'&since={since}'
        if until:
            url += f'&until={until}'

        headers = {**self.headers, 'Content-Type': 'application/json'}
        resp = self.session.get(url=url, headers=headers, auth=self.auth)

        # resp.raise_for_status()
        if resp.ok:
            for cmt in resp.json().get('values', {}):
                git_hash = cmt.get('id')
                yield GitCommit(
                    commit_url   = self.commit_url(git_hash),
                    git_hash     = git_hash,
                    message      = cmt.get('message'),
                    author_email = cmt.get('author', {}).get('emailAddress'),
                    author_name  = cmt.get('author', {}).get('displayName', 'unknown'),
                    jira_keys    = cmt.get('properties', {}).get('jira-key', []),
                )


    def create_tag(self, tag_name: str, commit_hash: str) -> bool:
        url = f'{self.url}rest/api/1.0/projects/{self.project}/repos/{self.repository}/tags'
        headers = {**self.headers, 'Content-Type': 'application/json'}

        payload = {
            'name': tag_name,
            'startPoint': commit_hash
        }

        resp = self.session.post(url=url, headers=headers, auth=self.auth, json=payload)

        if resp.status_code == 201:
            return True
        elif resp.status_code == 409:
            return False
        else:
            resp.raise_for_status()


    def commit_url(self, git_hash: str) -> str:
        return f'{self.url}projects/{self.project}/repos/{self.repository}/commits/{git_hash}'


    def compare_url(self, commit_a: str, commit_b: str) -> str:
        return f'{self.url}projects/{self.project}/repos/{self.repository}/compare/diff?targetBranch={commit_a}&sourceBranch={commit_b}'
