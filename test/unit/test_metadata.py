# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest

from dependency_injector import providers
from unittest.mock import MagicMock, patch

from rbbuild.core.paths import Paths
from rbbuild.core.toolchain import Toolchain
from rbbuild.package.metadata import Metadata

# Unit tests for rbbuild.package.metadata.Metadata.


def _make_paths(tmp_path):
    tc = Toolchain(tcid=None, toolchains_config={})
    source_path=tmp_path / 'project'
    source_path.mkdir(parents=True, exist_ok=True)
    return Paths(
        rbbuild_root=str(tmp_path / 'rbbuild'),
        source=str(source_path),
        staging_root='staging',
        build_root='obj',
        documentation_root='obj',
        dist=str(tmp_path / 'dist'),
        install_prefix=None,
        toolchain=tc,
    )


# ---------------------------------------------------------------------------
# Metadata — name
# ---------------------------------------------------------------------------

# 'name' taken directly from the config dict.
def test_metadata_name_from_config(tmp_path):
    m = Metadata({'name': 'mypkg'}, paths=_make_paths(tmp_path))
    assert m.name == 'mypkg'


# No 'name' in config and source is not a git repo -> name is name of current
# source project folder.
def test_metadata_name_no_git_repo(tmp_path):
    paths=_make_paths(tmp_path)
    m = Metadata({}, paths=paths)
    assert m.name is paths.source.name


# Name is extracted from the git remote URL when not in config.
def test_metadata_name_from_git(tmp_path):
    mock_remote = MagicMock()
    mock_remote.urls = iter(['ssh://git@example.com:7999/group/mypackage.git'])
    mock_repo = MagicMock()
    mock_repo.remotes = ['origin']
    mock_repo.remote.return_value = mock_remote
    with patch('rbbuild.package.metadata.Repo', return_value=mock_repo):
        m = Metadata({}, paths=_make_paths(tmp_path))
        assert m.name == 'mypackage'


# ---------------------------------------------------------------------------
# Metadata — version
# ---------------------------------------------------------------------------

# version_major/minor/revision/build keys map to the right components.
def test_metadata_version_from_explicit_keys(tmp_path):
    config = {
        'version_major': '3',
        'version_minor': '7',
        'version_revision': '100',
        'version_build': '42',
    }
    m = Metadata(config, paths=_make_paths(tmp_path))
    assert m.major == 3
    assert m.minor == 7
    assert m.revision == 100
    assert m.build == 42
    assert str(m.version) == '3.7.100.42'


# A plain 'version' dotted string is split into major/minor.
def test_metadata_version_from_dotted_string(tmp_path):
    m = Metadata({'version': '2.5'}, paths=_make_paths(tmp_path))
    assert m.major == 2
    assert m.minor == 5


# Without any version config the revision is computed as days since 2018-04-16.
def test_metadata_revision_auto_computed(tmp_path):
    m = Metadata({}, paths=_make_paths(tmp_path))
    assert m.revision > 0


# Without a build config the build component defaults to 0.
def test_metadata_build_defaults_to_zero(tmp_path):
    m = Metadata({}, paths=_make_paths(tmp_path))
    assert m.build == 0


# The local version of a development version uses the abbreviated branch.
@pytest.mark.parametrize('branch, expected', [
    ('RBBUILD-1234-my-ticket', '1.2.3.4.dev1+rbbuild.1234'),
    ('6-allow-filtering-by-branch-name', '1.2.3.4.dev1+6'),
    ('feature/some-work', '1.2.3.4.dev1+feature.some.work'),
])
def test_metadata_development_version_local(tmp_path, branch, expected):
    config = {
        'version_major': '1',
        'version_minor': '2',
        'version_revision': '3',
        'version_build': '4',
        'branch': branch,
    }
    m = Metadata(config, paths=_make_paths(tmp_path), development=True)
    assert str(m.version) == expected


@pytest.mark.parametrize('development', [True, False])
def test_metadata_development_from_selected_channel(app, development):
    channel = MagicMock(development=development)
    with app.core.channel.override(providers.Object(channel)):
        m = app.package.metadata()
    assert m.version.is_devrelease is development


def test_metadata_release_version_has_no_dev_or_local(tmp_path):
    config = {
        'version_major': '1',
        'version_minor': '2',
        'version_revision': '3',
        'version_build': '4',
        'branch': 'RBBUILD-1234-my-ticket',
    }
    m = Metadata(config, paths=_make_paths(tmp_path))
    assert str(m.version) == '1.2.3.4'


# ---------------------------------------------------------------------------
# Metadata — branch
# ---------------------------------------------------------------------------

# 'branch' taken directly from the config dict.
def test_metadata_branch_from_config(tmp_path):
    m = Metadata({'branch': 'my-feature'}, paths=_make_paths(tmp_path))
    assert m.branch == 'my-feature'


# No 'branch' in config and source is not a git repo -> falls back to 'local'.
def test_metadata_branch_no_git_repo(tmp_path):
    m = Metadata({}, paths=_make_paths(tmp_path))
    assert m.branch == 'local'


# Branch is read from git HEAD when not in config.
def test_metadata_branch_from_git(tmp_path):
    mock_repo = MagicMock()
    mock_repo.remotes = ['origin']
    mock_repo.head.is_detached = False
    mock_repo.head.ref.name = 'develop'
    with patch('rbbuild.package.metadata.Repo', return_value=mock_repo):
        m = Metadata({}, paths=_make_paths(tmp_path))
        assert m.branch == 'develop'

