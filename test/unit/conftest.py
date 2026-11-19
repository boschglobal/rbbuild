# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import shutil

from pathlib import Path

from rbbuild.container.application import Application
from rbbuild.container.configuration import RBBuildConfiguration
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.service.oss.fossid import FossID
from rbbuild.service.issuetracker.jira import Jira
from rbbuild.service.remote_service import AuthMethod


_CONFIG_PATH = Path('share/rbbuild/config')


@pytest.fixture
def fake_project(tmp_path):
    shutil.copytree('test/data/fake_project', tmp_path, dirs_exist_ok=True)
    yield tmp_path


def _make_app(tmp_path, monkeypatch, profile_name):
    user_home = tmp_path / 'home/user'
    shutil.copytree('test/data/user_home', user_home)
    monkeypatch.setenv('HOME', str(user_home))
    monkeypatch.delenv('RBB_CONFIG_PATH', raising=False)
    config = RBBuildConfiguration()
    config.load_configuration(Path('rbbuild'), _CONFIG_PATH)
    config.load_cli_profile(profile=profile_name)
    config.load_profile(
        profile_name=profile_name,
        rbbuild_config_path=_CONFIG_PATH,
        user_config_path=user_home / '.config/rbbuild',
    )
    config.load_cli(platform='linux')
    return Application(config=config)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    application = _make_app(tmp_path, monkeypatch, 'test')
    yield application
    application.unwire()


@pytest.fixture()
def app_test(tmp_path, monkeypatch):
    application = _make_app(tmp_path, monkeypatch, 'test')
    yield application
    application.unwire()


@pytest.fixture()
def fossid(app_test):
    fossid_cfgs = app_test.config.profile.oss()
    fossid_name = next(iter(fossid_cfgs))
    fossid_cfg  = fossid_cfgs[fossid_name]
    service_url = app_test.config.profile.services()[fossid_cfg['remote_service']]['url']
    yield FossID(
        name=fossid_name,
        url=service_url,
        auth_method=AuthMethod.BEARER_TOKEN,
        user='test_user',
        credentials='test_credentials',
        project_org_prefix=fossid_cfg['project_org_prefix'],
        truststore=False,
        op_mode = OperationMode(
            debug=False,
            verbose=False,
            force=False,
            ignore_errors=False,
            dry_run=False,
            offline=False,
            manifest_only=False,
            transitive=False,
        )
    )


@pytest.fixture()
def jira(app_test):
    issuetracker_cfgs = app_test.config.profile.issuetracker()
    jira_key  = next(iter(issuetracker_cfgs))
    jira_cfg  = issuetracker_cfgs[jira_key]
    service_url = app_test.config.profile.services()[jira_cfg['remote_service']]['url']
    yield Jira(
        key=jira_key,
        url=service_url,
        auth_method=AuthMethod.BEARER_TOKEN,
        user='test_user',
        credentials='test_credentials',
        truststore=False,
    )

