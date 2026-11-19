# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rbbuild.core.channel import Channel
from rbbuild.package.component import Component
from rbbuild.package.component_specifier import ComponentSpecifier
from rbbuild.package.package import Package
from rbbuild.service.remote_service import AuthMethod
from rbbuild.service.repository.artifactory import Artifactory
from rbbuild.service.repository.local_file_storage import LocalFileStorage
from rbbuild.service.repository.manager import RepositoryManager
from rbbuild.service.repository.repository import VersionConflictError


# Minimal stand-in for a Channel, only exposing the attributes
# _search()/_search_in_channel() actually read.
def _make_channel(chtype='rbbuild', redirect_repos=None):
    channel = MagicMock()
    channel.type = chtype
    channel.redirect_repos = redirect_repos or []
    return channel


# Build a minimal RepositoryManager without triggering __init__ (same
# pattern as test_promote.py's _make_repoman()). toolchain_factory is a
# simple callable(tcid=...) -> a fake Toolchain-like object, so tests can
# assert on the exact identity/string that was tried per configured toolchain.
def _make_repoman(service, toolchains_config):
    repoman = RepositoryManager.__new__(RepositoryManager)
    repoman.deps_parser = MagicMock()
    repoman.deps_parser.toolchain_factory = lambda tcid: tcid
    repoman.selected_channel = None
    repoman.target_toolchain = None
    repoman._toolchains_config = toolchains_config
    repoman.service = lambda channel: service
    return repoman


def _make_pkg(name='mypkg', version='1.0', toolchain=None):
    pkg = Package(name=name, version=version)
    pkg.toolchain = toolchain
    return pkg


# ---------------------------------------------------------------------------
# RepositoryManager.search_toolchains()
# ---------------------------------------------------------------------------

# When pkg.toolchain is already set, it must be honored as-is (single
# search() call, no iteration over the configured toolchains at all).
def test_search_toolchains_honors_explicit_toolchain_constraint():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    found = Package(name='mypkg', version='1.0')
    service.find_package.return_value = found

    repoman = _make_repoman(service, toolchains_config={'linux-native': {}, 'win32-mingw': {}})
    pkg = _make_pkg(toolchain='linux-native')

    results = list(repoman.search_toolchains(pkg=pkg, channel=channel))

    assert results == [found]
    service.find_package.assert_called_once()
    assert service.find_package.call_args[0][0].toolchain == 'linux-native'


# When pkg.toolchain is not set, every toolchain configured in the profile is
# tried via the unmodified search()/find_package() path - the package is
# found even though it was never published for the "default" toolchain.
def test_search_toolchains_tries_all_configured_toolchains_when_unset():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']

    def fake_find_package(qpkg):
        # only published for win32-mingw, not linux-native
        if qpkg.toolchain == 'win32-mingw':
            return Package(name='mypkg', version='1.0')
        return None

    service.find_package.side_effect = fake_find_package

    repoman = _make_repoman(service, toolchains_config={'linux-native': {}, 'win32-mingw': {}})
    pkg = _make_pkg(toolchain=None)

    results = list(repoman.search_toolchains(pkg=pkg, channel=channel))

    assert len(results) == 1
    assert results[0].toolchain == 'win32-mingw'


# If the package is published for more than one configured toolchain, every
# variant is returned (not just the first match).
def test_search_toolchains_returns_every_matching_toolchain():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.side_effect = lambda qpkg: Package(name='mypkg', version='1.0')

    repoman = _make_repoman(service, toolchains_config={'linux-native': {}, 'win32-mingw': {}})
    pkg = _make_pkg(toolchain=None)

    results = list(repoman.search_toolchains(pkg=pkg, channel=channel))

    assert sorted(r.toolchain for r in results) == ['linux-native', 'win32-mingw']


# No configured toolchain has a match → empty result, not a crash.
def test_search_toolchains_returns_empty_when_no_toolchain_matches():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.return_value = None

    repoman = _make_repoman(service, toolchains_config={'linux-native': {}, 'win32-mingw': {}})
    pkg = _make_pkg(toolchain=None)

    results = list(repoman.search_toolchains(pkg=pkg, channel=channel))

    assert results == []


# ---------------------------------------------------------------------------
# RepositoryManager.list_toolchains() - find_package() call signature
# ---------------------------------------------------------------------------

# Regression test: list_toolchains() must call service.find_package() with a
# single Package argument (matching Repository.find_package(self, pkg)), not
# positional (name, version, toolchain) - previously this raised TypeError
# whenever a toolchain's manifest existed remotely but was not yet cached.
def test_list_toolchains_caches_uncached_remote_manifest():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.cache.list_manifest_names.return_value = []
    service.list_manifest_names.return_value = ['mypkg-1.0-linux-native-manifest.json']

    repoman = _make_repoman(service, toolchains_config={})

    results = list(repoman.list_toolchains('mypkg', '1.0', channel=channel))

    assert results == ['linux-native']
    service.find_package.assert_called_once()
    called_pkg = service.find_package.call_args[0][0]
    assert isinstance(called_pkg, Package)
    assert called_pkg.name == 'mypkg'
    assert called_pkg.version == '1.0'
    assert called_pkg.toolchain == 'linux-native'


# ---------------------------------------------------------------------------
# RepositoryManager._search_in_channel() light vs. non-light toolchain handling
# ---------------------------------------------------------------------------

# search_versions() (light=True) never downloads/parses a manifest, so there
# is nothing to verify a guessed toolchain against - it must not default an
# unset pkg.toolchain to self.target_toolchain, otherwise every listed
# version looks like it has a confirmed toolchain even when it doesn't.
def test_search_versions_does_not_default_toolchain_when_unset():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']

    repoman = _make_repoman(service, toolchains_config={})
    repoman.target_toolchain = 'linux-native'  # would previously leak into results
    pkg = _make_pkg(toolchain=None)

    results = list(repoman.search_versions(pkg=pkg, channel=channel))

    assert len(results) == 1
    assert results[0].toolchain is None
    service.find_package.assert_not_called()


# search_versions() must still carry through an explicitly set pkg.toolchain
# as-is (used by search_toolchains() to tag each per-toolchain listing).
def test_search_versions_keeps_explicit_toolchain():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']

    repoman = _make_repoman(service, toolchains_config={})
    pkg = _make_pkg(toolchain='win32-mingw')

    results = list(repoman.search_versions(pkg=pkg, channel=channel))

    assert len(results) == 1
    assert results[0].toolchain == 'win32-mingw'


# search() (light=False) must keep defaulting an unset toolchain to
# self.target_toolchain - only the light branch's behavior changed.
def test_search_still_defaults_toolchain_when_unset():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.return_value = Package(name='mypkg', version='1.0')

    repoman = _make_repoman(service, toolchains_config={})
    repoman.target_toolchain = 'linux-native'
    pkg = _make_pkg(toolchain=None)

    results = list(repoman.search(pkg=pkg, channel=channel))

    assert len(results) == 1
    assert results[0].toolchain == 'linux-native'
    assert service.find_package.call_args[0][0].toolchain == 'linux-native'


# Component flags from the requesting package's specifier are applied to the
# matching components of the found package; unmatched components are dropped.
def test_search_applies_component_specifier_flags():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    found = Package(name='mypkg', version='1.0')
    found.components = [
        Component(name='dev', suffix='tar.xz'),
        Component(name='prod', suffix='tar.xz'),
    ]
    service.find_package.return_value = found

    repoman = _make_repoman(service, toolchains_config={})
    pkg = _make_pkg(toolchain='linux-native')
    pkg.component_specifier = ComponentSpecifier(
        components=['dev'], suffixes=None, build_only=True, traverse=False)

    results = list(repoman.search(pkg=pkg, channel=channel))

    assert [c.name for c in results[0].components] == ['dev']
    assert results[0].components[0].build_only is True
    assert results[0].components[0].traverse is False


def test_search_keeps_default_traverse_for_matching_components():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    found = Package(name='mypkg', version='1.0')
    found.components = [Component(name='dev', suffix='tar.xz')]
    service.find_package.return_value = found

    repoman = _make_repoman(service, toolchains_config={})
    pkg = _make_pkg(toolchain='linux-native')
    pkg.component_specifier = ComponentSpecifier(
        components=['dev'], suffixes=None, build_only=False, traverse=True)

    results = list(repoman.search(pkg=pkg, channel=channel))

    assert results[0].components[0].build_only is False
    assert results[0].components[0].traverse is True


# ---------------------------------------------------------------------------
# RepositoryManager.search() with redirect_repos (real Artifactory, mocked HTTP)
# ---------------------------------------------------------------------------

_ARTIFACTORY_URL = 'https://artifactory.test/artifactory/'

_REDIRECT_CHANNELS = {
    'dev': {
        'type':           'rbbuild',
        'remote_service': 'svc',
        'repository':     'dev-local',
        'root_path':      'components',
        'redirect_repos': ['rel'],
    },
    'rel': {
        'type':           'rbbuild',
        'remote_service': 'svc',
        'repository':     'rel-local',
        'root_path':      'components',
    },
}


# Manifest stand-in: the mocked manifest body is just the version string.
class _FakeManifest:
    def make_filename(self, name, version, toolchain, legacy=False):
        suffix = f'{toolchain}-' if not legacy else ''
        return f'{name}-{version}-{suffix}manifest.json'

    def load(self, path):
        return Package(name='mypkg', version=Path(path).read_text())


def _make_channel_by_name(name, tmp_path):
    return Channel(
        name=name,
        default_channel='dev',
        channels_config=_REDIRECT_CHANNELS,
        source_path=str(tmp_path),
    )


# RepositoryManager wired to real Artifactory services for the 'dev' and
# 'rel' channels. Everything under <repository>/ answers 404 unless
# published with _publish().
@pytest.fixture
def redirect_repoman(tmp_path, requests_mock):
    tmp_dir = tmp_path / 'tmp'
    tmp_dir.mkdir()
    manifest = _FakeManifest()
    deps_parser = MagicMock()
    deps_parser.channel_factory = (
        lambda name: _make_channel_by_name(name, tmp_path))

    for repository in ('dev-local', 'rel-local'):
        requests_mock.get(re.compile(f'/{repository}/'), status_code=404)

    return RepositoryManager(
        deps_parser=deps_parser,
        selected_channel=_make_channel_by_name('dev', tmp_path),
        target_toolchain='linux-native',
        op_mode=MagicMock(),
        cache_provider=lambda channel: LocalFileStorage(
            channel=channel, dist_path=tmp_path / 'dist', manifest=manifest),
        services_config={
            'svc': {'type': 'artifactory', 'url': _ARTIFACTORY_URL},
        },
        user_config={},
        toolchains_config={},
        artifactory=lambda **kwargs: Artifactory(
            manifest=manifest,
            temp_folder=MagicMock(path=tmp_dir),
            op_mode=MagicMock(),
            **kwargs,
        ),
    )


def _publish(requests_mock, repository, version):
    requests_mock.get(
        f'{_ARTIFACTORY_URL}{repository}/components/mypkg/{version}/'
        f'mypkg-{version}-linux-native-manifest.json',
        text=version,
    )


def _search_pinned(repoman, tmp_path, version='1.0'):
    return list(repoman.search(
        pkg=_make_pkg(version=version),
        channel=_make_channel_by_name('dev', tmp_path),
    ))


# Reported bug: pkq -l <pkg>-<ver> --channel buildcore-development fails
# with a 404 on the release channel although the package exists in the
# development channel.
def test_search_pinned_version_only_in_primary_channel(
    redirect_repoman, requests_mock, tmp_path
):
    _publish(requests_mock, 'dev-local', '1.0')

    results = _search_pinned(redirect_repoman, tmp_path)

    assert [(r.version, r.channel.name) for r in results] == [('1.0', 'dev')]


# The reverse: only published to the redirect channel.
def test_search_pinned_version_only_in_redirect_channel(
    redirect_repoman, requests_mock, tmp_path
):
    _publish(requests_mock, 'rel-local', '1.0')

    results = _search_pinned(redirect_repoman, tmp_path)

    assert [(r.version, r.channel.name) for r in results] == [('1.0', 'rel')]


# A pinned version is unique: if the primary channel has it, the redirect
# channel is not consulted at all.
def test_search_pinned_version_in_both_channels_returns_primary_only(
    redirect_repoman, requests_mock, tmp_path
):
    _publish(requests_mock, 'dev-local', '1.0')
    _publish(requests_mock, 'rel-local', '1.0')
    requests_mock.reset_mock()

    results = _search_pinned(redirect_repoman, tmp_path)

    assert [r.channel.name for r in results] == ['dev']
    assert not any(
        'rel-local' in req.url for req in requests_mock.request_history)


# Not published anywhere: not found, not an error.
def test_search_pinned_version_in_no_channel(redirect_repoman, tmp_path):
    assert _search_pinned(redirect_repoman, tmp_path) == []


# ---------------------------------------------------------------------------
# RepositoryManager.search() - packages without toolchain
# ---------------------------------------------------------------------------

# Selected toolchain first, then the toolchain-less package.
def test_search_falls_back_to_package_without_toolchain():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    tried = []

    def find_package(qpkg):
        tried.append(qpkg.toolchain)
        return None if qpkg.toolchain else Package(name='mypkg', version='1.0')

    service.find_package.side_effect = find_package

    repoman = _make_repoman(service, toolchains_config={})
    repoman.target_toolchain = 'linux-native'

    results = list(repoman.search(pkg=_make_pkg(toolchain=None), channel=channel))

    assert len(results) == 1
    assert results[0].toolchain is None
    assert tried == ['linux-native', None]


def test_search_prefers_package_with_selected_toolchain():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.side_effect = lambda qpkg: Package(name='mypkg', version='1.0')

    repoman = _make_repoman(service, toolchains_config={})
    repoman.target_toolchain = 'linux-native'

    results = list(repoman.search(pkg=_make_pkg(toolchain=None), channel=channel))

    assert results[0].toolchain == 'linux-native'
    service.find_package.assert_called_once()


def test_search_without_toolchain_not_found_anywhere():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.return_value = None

    repoman = _make_repoman(service, toolchains_config={})
    repoman.target_toolchain = 'linux-native'

    assert list(repoman.search(pkg=_make_pkg(toolchain=None), channel=channel)) == []


# The toolchain-less package is the same result for every configured toolchain.
def test_search_toolchains_lists_package_without_toolchain_once():
    channel = _make_channel()
    service = MagicMock()
    service.channel = channel
    service.list_versions.return_value = ['1.0']
    service.find_package.side_effect = (
        lambda qpkg: None if qpkg.toolchain else Package(name='mypkg', version='1.0'))

    repoman = _make_repoman(service, toolchains_config={'linux-native': {}, 'win32-mingw': {}})

    results = list(repoman.search_toolchains(pkg=_make_pkg(toolchain=None), channel=channel))

    assert [r.toolchain for r in results] == [None]


# ---------------------------------------------------------------------------
# RepositoryManager.service()
# ---------------------------------------------------------------------------

def _make_repoman_for_service(services_config, **providers):
    return RepositoryManager(
        deps_parser=MagicMock(),
        selected_channel=MagicMock(),
        target_toolchain=MagicMock(),
        op_mode=MagicMock(),
        cache_provider=MagicMock(),
        services_config=services_config,
        user_config={'svc': {'user': 'u', 'credentials': 'c'}},
        toolchains_config={},
        **providers,
    )


def test_service_dispatches_to_provider_by_type():
    provider = MagicMock()
    repoman = _make_repoman_for_service(
        {'svc': {'type': 'plugintype', 'url': 'https://x/'}},
        plugintype=provider,
    )
    channel = MagicMock(remote_service='svc')

    result = repoman.service(channel)

    assert result is provider.return_value
    assert provider.call_args.kwargs['url'] == 'https://x/'
    assert provider.call_args.kwargs['user'] == 'u'
    assert provider.call_args.kwargs['credentials'] == 'c'


def test_service_passes_auth_method_from_config():
    provider = MagicMock()
    repoman = _make_repoman_for_service(
        {'svc': {'type': 'plugintype', 'url': 'https://x/', 'auth-method': 'bearer-token'}},
        plugintype=provider,
    )
    repoman.service(MagicMock(remote_service='svc'))
    assert provider.call_args.kwargs['auth_method'] == AuthMethod.BEARER_TOKEN


def test_service_auth_method_undefined_is_none():
    provider = MagicMock()
    repoman = _make_repoman_for_service(
        {'svc': {'type': 'plugintype', 'url': 'https://x/'}},
        plugintype=provider,
    )
    repoman.service(MagicMock(remote_service='svc'))
    assert provider.call_args.kwargs['auth_method'] == AuthMethod.NONE


def test_service_truststore_undefined_is_false():
    provider = MagicMock()
    repoman = _make_repoman_for_service(
        {'svc': {'type': 'plugintype', 'url': 'https://x/'}},
        plugintype=provider,
    )
    repoman.service(MagicMock(remote_service='svc'))
    assert provider.call_args.kwargs['truststore'] is False


def test_service_passes_truststore_from_config():
    provider = MagicMock()
    repoman = _make_repoman_for_service(
        {'svc': {'type': 'plugintype', 'url': 'https://x/', 'truststore': True}},
        plugintype=provider,
    )
    repoman.service(MagicMock(remote_service='svc'))
    assert provider.call_args.kwargs['truststore'] is True


def test_service_unavailable_type_raises_lookup_error():
    repoman = _make_repoman_for_service({'svc': {'type': 'csi', 'url': 'https://x/'}})
    channel = MagicMock(remote_service='svc')

    with pytest.raises(LookupError, match='"csi".*not available'):
        repoman.service(channel)


# ---------------------------------------------------------------------------
# RepositoryManager.upload()
# ---------------------------------------------------------------------------

# Build a minimal RepositoryManager for upload() tests, with a fixed service
# and op_mode (upload() reads op_mode.force to decide skip-when-disabled).
def _make_repoman_for_upload(service, force=False):
    repoman = RepositoryManager.__new__(RepositoryManager)
    repoman.service = lambda channel: service
    repoman.op_mode = MagicMock(force=force)
    return repoman


def _make_pkg_with_manifest(n_components=2):
    channel = MagicMock()
    channel.publish = True
    pkg = Package(name='mypkg', version='1.0')
    pkg.channel = channel
    pkg.components = [
        Component(name=f'comp{i}', suffix='tar', filename=f'comp{i}.tar')
        for i in range(n_components)
    ]
    pkg.manifest = Component(name='manifest', suffix='json', filename='mypkg-1.0-manifest.json')
    return pkg


# Every component (including the manifest) is uploaded via the same
# upload_component() call, components first and the manifest last.
def test_upload_uploads_components_then_manifest():
    service = MagicMock()
    repoman = _make_repoman_for_upload(service)
    pkg = _make_pkg_with_manifest()

    list(repoman.upload(pkg))

    assert service.upload_component.call_count == 3
    uploaded = [call.kwargs['component'] for call in service.upload_component.call_args_list]
    assert uploaded == [*pkg.components, pkg.manifest]


# A VersionConflictError raised for any component (including the manifest)
# propagates through upload() so callers (RBBuild.publish()) can react to it.
def test_upload_propagates_version_conflict():
    service = MagicMock()
    pkg = _make_pkg_with_manifest(n_components=0)
    service.upload_component.side_effect = [VersionConflictError('conflict')]
    repoman = _make_repoman_for_upload(service)

    with pytest.raises(VersionConflictError):
        list(repoman.upload(pkg))


