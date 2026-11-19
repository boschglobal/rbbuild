# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import os
from unittest.mock import patch

from rbbuild.service.ci.jenkins import Jenkins
from rbbuild.service.ci.github_actions import GitHubActions
from rbbuild.service.remote_service import AuthMethod

# Unit tests for the CIService.job_url() implementations (Jenkins,
# GitHub Actions). job_url() returns the URL of the build currently
# executing under that CI system, detected purely from the environment.


def _jenkins(key='EXAMPLE'):
    return Jenkins(key=key, url='https://jenkins.example.com/', auth_method=AuthMethod.NONE, user=None, credentials=None, truststore=False)


def _github_actions(key='EXAMPLE'):
    return GitHubActions(key=key, url='', auth_method=AuthMethod.NONE, user=None, credentials=None, truststore=False)


def test_jenkins_job_url_from_build_url_env():
    env = {'BUILD_URL': 'https://jenkins.example.com/job/pkg/12/'}
    with patch.dict(os.environ, env, clear=True):
        assert _jenkins().job_url() == env['BUILD_URL']


def test_jenkins_job_url_none_without_build_url():
    with patch.dict(os.environ, {}, clear=True):
        assert _jenkins().job_url() is None


def test_github_actions_job_url_from_env():
    env = {
        'GITHUB_SERVER_URL': 'https://github.com',
        'GITHUB_REPOSITORY': 'boschglobal/rbbuild',
        'GITHUB_RUN_ID': '4242',
    }
    with patch.dict(os.environ, env, clear=True):
        assert _github_actions().job_url() == 'https://github.com/boschglobal/rbbuild/actions/runs/4242'


def test_github_actions_job_url_none_without_env():
    with patch.dict(os.environ, {}, clear=True):
        assert _github_actions().job_url() is None
