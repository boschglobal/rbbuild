#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re

from typing import Iterator

from rbbuild.service.remote_service import AuthMethod

from .git_repository import GitRepository, GitCommit


class GitHub(GitRepository):
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


    def get_commits(self, since=None, until=None, limit=100) -> Iterator[GitCommit]:
        # From: https://docs.github.com/en/rest/commits/commits?apiVersion=2022-11-28#list-commits
        if not since:
            since = ''
        if not until:
            until = ''

        url = f'{self.url}repos/{self.project}/{self.repository}/compare/{since}...{until}?per_page={limit}'
        headers = {**self.headers, 'Content-Type': 'application/json'}
        resp = self.session.get(url=url, headers=headers, auth=self.auth)

        if resp.ok:
            for cmt in resp.json().get('commits', {}):
                message = cmt.get('commit', {}).get('message')
                jira_keys = list(set(re.findall(r'[\w]+-[\d]+', message)))
                git_hash = cmt.get('sha')
                yield GitCommit(
                    commit_url   = self.commit_url(git_hash),
                    git_hash     = git_hash,
                    message      = message,
                    author_email = cmt.get('commit', {}).get('author', {}).get('email'),
                    author_name  = cmt.get('commit', {}).get('author', {}).get('name', 'unknown'),
                    jira_keys    = jira_keys,
                )


    def create_tag(self, tag_name: str, commit_hash: str) -> bool:
        raise NotImplementedError(f'create_tag is not implemented for GitHub service {self.url}')


    def commit_url(self, git_hash: str) -> str:
        return f'https://github.com/{self.project}/{self.repository}/commit/{git_hash}'


    def compare_url(self, commit_a: str, commit_b: str) -> str:
        return f'https://github.com/{self.project}/{self.repository}/compare/{commit_a}...{commit_b}'


    #def git_commit_url(self, pkg: Package, commit: str) -> str:
    #    url = f'{self.config.url}repos/{pkg.purl.namespace}/{pkg.purl.name}/commits/{quote_plus(commit)}'
    #    return url
    #
    #
    ## Returns a list of version strings
    #def list(self, pkg: Package) -> List[str]:
    #    url = self.git_commit_url(pkg, pkg.version)
    #    headers = {**self.headers, 'Content-Type': 'application/json'}
    #    resp = requests.get(url=url, headers=headers, auth=self.auth)
    #    resp.raise_for_status()
    #
    #    versions = []
    #    for git_hash in resp.json().get('sha'):
    #        versions.append(f'{pkg.version}+{git_hash}')
    #
    #    return versions
    #
    #
    #def do_download(self, purl: PackageURL, path: str, dest_path: Path) -> Iterator[Path]:
    #    # Avoid duplicate slashes in URL
    #    if path.startswith('/'):
    #        path = path[1:]
    #
    #    url = f'{self.config.url}repos/{purl.namespace}/{purl.name}/contents/{path}?ref={quote_plus(purl.version)}'
    #    headers = {**self.headers, 'Content-Type': 'application/json'}
    #    resp = requests.get(url=url, headers=headers, auth=self.auth)
    #
    #    resp.raise_for_status()
    #    data = resp.json()
    #
    #    # 'lines' indicates that the response is a file
    #    if type(data) is not list:
    #        out_file = dest_path / path
    #        out_file.parent.mkdir(parents=True, exist_ok=True)
    #        with open(out_file, 'wb') as fd:
    #            fd.write(base64.b64decode(data['content']))
    #        yield out_file
    #
    #    # Requested a path - recursive call
    #    else:
    #        for child in data:
    #            yield from self.do_download( purl,
    #                                         f'{path}/{child["name"]}',
    #                                         dest_path )

