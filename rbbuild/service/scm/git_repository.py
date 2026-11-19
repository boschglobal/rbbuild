#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from abc import ABCMeta, abstractmethod
from typing import Iterator, List
from dataclasses import dataclass

from rbbuild.service.remote_service import RemoteService, AuthMethod


@dataclass
class GitCommit:
    commit_url: str
    git_hash: str
    message: str
    author_email: str
    author_name: str
    jira_keys: List[str]


class GitRepository(RemoteService, metaclass=ABCMeta):
    def __init__(
        self,
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


    @abstractmethod
    def get_commits(self, since=None, until=None, limit=100) -> Iterator[GitCommit]:
        pass


    @abstractmethod
    def create_tag(self, tag_name: str, commit_hash: str) -> bool:
        pass


    # Browsable (web UI) URL for a single commit.
    @abstractmethod
    def commit_url(self, git_hash: str) -> str:
        pass


    # Browsable (web UI) URL comparing two commits/branches.
    @abstractmethod
    def compare_url(self, commit_a: str, commit_b: str) -> str:
        pass

