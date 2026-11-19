# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import json
import shutil

from pathlib import Path

from rbbuild.container.application import Application
from rbbuild.container.configuration import RBBuildConfiguration
from rbbuild.package.license import License
from rbbuild.package.package import Package, PackageInstallAction, Supplier, Tool
from rbbuild.package.component import Component
from rbbuild.service.issuetracker.issuetracker_manager import Issue

@pytest.fixture
def app(tmp_path, monkeypatch):
    user_home = tmp_path / 'home/user'
    shutil.copytree('test/data/user_home', user_home)
    monkeypatch.setenv('HOME', str(user_home))
    config_path = Path('share/rbbuild/config')
    rbb_root = Path('rbbuild')
    config = RBBuildConfiguration()
    config.load_configuration(rbb_root, config_path)
    config.load_profile(profile_name='test', rbbuild_config_path=config_path, user_config_path=user_home / '.config/rbbuild')
    config.load_cli(platform='linux')
    monkeypatch.delenv('RBB_CONFIG_PATH', raising=False)
    application = Application(config=config)
    yield application
    application.unwire()


@pytest.fixture
def manifest_parser(app):
    yield app.package.parser()


@pytest.fixture
def deps_parser(app):
    yield app.deps.parser()



def test_construction():
    pkg = Package()
    assert pkg
    # None default values (most important)
    assert pkg.name is None
    assert pkg.version is None
    assert pkg.channel is None
    assert pkg.toolchain is None
    assert pkg.branch is None
    # non-None default values
    assert pkg.installdir == ''
    assert pkg.namespace == ''
    assert pkg.components == []
    assert pkg.dependencies == {}
    assert pkg.install_action == PackageInstallAction.DEFAULT


# A dash-free name uses '-' as separator (the long-standing convention);
# a name that itself contains a dash uses '@' instead, since
# DepsParser.parse_item() only splits a plain "name-version" string on
# its first dash - a dashed name would otherwise round-trip incorrectly.
def test_str_uses_dash_separator_for_plain_name():
    pkg = Package('mypkg', '1.0.0')
    assert str(pkg) == 'mypkg-1.0.0'


def test_str_uses_at_separator_for_dashed_name():
    pkg = Package('my-package', '1.0.0')
    assert str(pkg) == 'my-package@1.0.0'


def test_str_dashed_name_round_trips_through_deps_parser(deps_parser):
    pkg = Package('my-package', '1.0.0')
    reparsed = deps_parser.parse_item(str(pkg))
    assert reparsed.name == 'my-package'
    assert reparsed.version == '1.0.0'


_EXAMPLE_COMPONENTS = Path('test/data/fake_artifactory/example-development-local/components')


def _load_manifest(manifest_parser, path):
    with open(path, 'r') as jfd:
        return manifest_parser.parse(json.load(jfd))


@pytest.mark.parametrize( 'manifest_path, pkgstr, toolchain',
                          [
                              ( 'libfoo/2.0.0.3/libfoo-2.0.0.3-linux-native-manifest.json',
                                'libfoo-2.0.0.3',
                                'linux-native' ),
                              ( 'libfoo/1.0.0.1/libfoo-1.0.0.1-win32-mingw-manifest.json',
                                'libfoo-1.0.0.1',
                                'win32-mingw' ),
                              ( 'libbar/3.0.0.3/libbar-3.0.0.3-linux-ubuntu-armhf-manifest.json',
                                'libbar-3.0.0.3',
                                'linux-ubuntu-armhf' ),
                              ( 'libbaz/2.0.0.5/libbaz-2.0.0.5-linux-native-manifest.json',
                                'libbaz-2.0.0.5',
                                'linux-native' ),
                          ])
def test_load_from_manifest(manifest_parser, manifest_path, pkgstr, toolchain):
    pkg = _load_manifest(manifest_parser, _EXAMPLE_COMPONENTS / manifest_path)
    assert pkg
    assert str(pkg) == pkgstr
    assert str(pkg.toolchain) == toolchain
    assert pkg.channel.name == 'example-development'


@pytest.mark.parametrize( 'manifest_path, child_pkgs',
                          [
                              ('libfoo/2.0.0.3/libfoo-2.0.0.3-linux-native-manifest.json', []),
                              ('libbar/2.0.0.2/libbar-2.0.0.2-linux-native-manifest.json',
                                  ['libfoo@linux-native', 'testtool@linux-native']),
                              ('libbar/3.0.0.3/libbar-3.0.0.3-linux-ubuntu-armhf-manifest.json',
                                  ['libfoo@linux-ubuntu-armhf']),
                          ])
def test_manifest_dependencies(manifest_parser, manifest_path, child_pkgs):
    pkg = _load_manifest(manifest_parser, _EXAMPLE_COMPONENTS / manifest_path)
    assert sorted(pkg.dependencies) == child_pkgs


# Dependencies of dependencies are read recursively; build-only components
# are marked in the child packages.
def test_manifest_nested_dependencies(manifest_parser):
    pkg = _load_manifest(
        manifest_parser,
        _EXAMPLE_COMPONENTS / 'libbar/2.0.0.2/libbar-2.0.0.2-linux-native-manifest.json')
    testtool = pkg.dependencies['testtool@linux-native']
    assert testtool.build_only is True
    assert sorted(testtool.dependencies) == ['testlib@linux-native']
    assert testtool.dependencies['testlib@linux-native'].build_only is True
    assert pkg.dependencies['libfoo@linux-native'].build_only is False


@pytest.mark.parametrize( 'manifest_path, components',
                          [
                              ('libfoo/2.0.0.3/libfoo-2.0.0.3-linux-native-manifest.json',
                                  ['prod', 'dev', 'licenses', 'debug']),
                              ('libbaz/2.0.0.5/libbaz-2.0.0.5-linux-native-manifest.json', []),
                          ]
                        )
def test_manifest_components(manifest_parser, manifest_path, components):
    pkg = _load_manifest(manifest_parser, _EXAMPLE_COMPONENTS / manifest_path)
    assert [comp.name for comp in pkg.components] == components
    for comp in pkg.components:
        assert comp.suffix == 'tar.xz'
        assert comp.filename
        assert comp.checksum
        assert not comp.build_only
        assert comp.localpath is None


@pytest.mark.parametrize( 'entry_a, entry_b, pkg_exp',
                          [
                              ('libfoo-1.0.0.1', 'libfoo-1.0.0.1', 'libfoo-1.0.0.1'),
                              ('libfoo-2.0.0.3', 'libfoo',          'libfoo-2.0.0.3'),
                              ('libfoo-1.0.0.1', 'libfoo',          'libfoo-1.0.0.1'),
                              ('libfoo',         'libfoo-1.0.0.1', 'libfoo-1.0.0.1'),
                              ('libfoo',         'libfoo',         'libfoo'),
                          ]
                        )
def test_package_merge_versions(deps_parser, entry_a, entry_b, pkg_exp):
    pkg_a = deps_parser.parse_item(entry_a)
    pkg_b = deps_parser.parse_item(entry_b)
    pkg_a.merge(pkg_b)
    assert str(pkg_a) == pkg_exp


@pytest.mark.parametrize( 'entry_a, entry_b',
                          [
                              ('libfoo-1.0.0.1',  'libfoo-2.0.0.3'),
                              ('libbar-1.1.0.2',  'libbar-1.0.0.1'),
                              ('openssl-1.0.403-master.17',  'openssl-1.2.3.4'),
                          ]
                        )
def test_package_merge_conflict(deps_parser, entry_a, entry_b):
    pkg_a = deps_parser.parse_item(entry_a)
    pkg_b = deps_parser.parse_item(entry_b)
    with pytest.raises(RuntimeError):
        pkg_a.merge(pkg_b)


# --- version_constraints setter ---

def test_version_constraints_invalid_type():
    pkg = Package()
    with pytest.raises(SyntaxError):
        pkg.version_constraints = 42


# --- branch_abbreviated ---

def test_branch_abbreviated_special_chars():
    # '/' is replaced with '_'
    assert Issue.branch_abbreviated('test/branch-name') == 'test_branch-name'


def test_branch_abbreviated_jira_ticket():
    # Trailing ticket text is stripped
    assert Issue.branch_abbreviated('PROJECT-1234-some-description') == 'PROJECT-1234'


def test_branch_abbreviated_github_issue():
    assert Issue.branch_abbreviated('6-allow-filtering-by-branch-name') == '6'


# --- licenses setter ---


def test_licenses_dict_with_license_key():
    # CycloneDX-wrapped format: License.coerce handles the 'license' wrapper key
    licenses = License.coerce([{'license': {'id': 'MIT'}}])
    assert len(licenses) == 1
    assert licenses[0].id == 'MIT'


def test_licenses_dict_without_license_key():
    # Bare dict format: keyword args passed directly to License
    licenses = License.coerce([{'id': 'Apache-2.0'}])
    assert len(licenses) == 1
    assert licenses[0].id == 'Apache-2.0'


def test_licenses_invalid_type_in_list():
    with pytest.raises(SyntaxError):
        License.coerce([42])


def test_licenses_expression_mode_multiple_items():
    with pytest.raises(SyntaxError):
        # Only one expression item is allowed
        License.coerce([License(expression='MIT'), License(expression='Apache-2.0')])


# --- purl setter ---

def test_purl_setter_invalid_type():
    pkg = Package()
    with pytest.raises(SyntaxError):
        pkg.purl = 12345


# --- supplier constructor ---

def test_supplier_from_dict():
    # Supplier is a plain dataclass constructor
    supplier = Supplier(name='Example', email='info@example.com')
    assert isinstance(supplier, Supplier)
    assert supplier.name == 'Example'
    assert supplier.email == 'info@example.com'


# --- tools constructor ---

def test_tool_from_dict():
    # Tool is a plain dataclass constructor
    tool = Tool(vendor='Example', name='rbbuild', version='1.0.0')
    assert isinstance(tool, Tool)
    assert tool.name == 'rbbuild'


# --- merge: branch mismatch ---

def test_package_merge_branch_conflict(deps_parser):
    pkg_a = deps_parser.parse_item('libfoo-1.0.0.1')
    pkg_b = deps_parser.parse_item('libfoo-1.0.0.1')
    pkg_a.branch = 'master'
    pkg_b.branch = 'develop'
    with pytest.raises(RuntimeError):
        pkg_a.merge(pkg_b)


# --- build_only property ---

def test_build_only_all_build_only():
    pkg = Package()
    pkg.components = [
        Component(name='dev', suffix='tar.xz', filename='pkg-1.0-dev.tar.xz', checksum='abc', build_only=True),
        Component(name='prod', suffix='tar.xz', filename='pkg-1.0-prod.tar.xz', checksum='def', build_only=True),
    ]
    assert pkg.build_only is True


def test_build_only_not_all_build_only():
    pkg = Package()
    pkg.components = [
        Component(name='dev', suffix='tar.xz', filename='pkg-1.0-dev.tar.xz', checksum='abc', build_only=True),
        Component(name='prod', suffix='tar.xz', filename='pkg-1.0-prod.tar.xz', checksum='def', build_only=False),
    ]
    assert pkg.build_only is False


# --- license property (singular) ---

# pkg.license = value uses License.coerce() and returns the first license entry
def test_license_setter():
    pkg = Package()
    pkg.license = 'MIT'   # string form → delegates to licenses.setter
    assert pkg.license is not None
    assert pkg.license.expression == 'MIT'


# --- Package.__eq__ ---

def test_package_equality():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='mypkg', version='1.0.0')
    assert pkg1 == pkg2


def test_package_inequality():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='other', version='1.0.0')
    assert pkg1 != pkg2


# --- merge: branch pass (other.branch is None, no mismatch) ---

def test_merge_branch_pass():
    pkg_a = Package(name='nng', version='1.0.0')
    pkg_b = Package(name='nng', version='1.0.0')
    pkg_a.branch = 'master'
    pkg_b.branch = None    # no branch in other → skip update, no error
    pkg_a.merge(pkg_b)
    assert pkg_a.branch == 'master'


# --- merge: existing dependency merged ---

def test_merge_existing_dependency():
    child_a = Package(name='dep', version=None)
    child_b = Package(name='dep', version='1.0.0')

    pkg_a = Package(name='parent')
    pkg_a.dependencies = {'dep': child_a}

    pkg_b = Package(name='parent')
    pkg_b.dependencies = {'dep': child_b}

    pkg_a.merge(pkg_b)
    # The child in pkg_a should now have the version from child_b
    assert pkg_a.dependencies['dep'].version == '1.0.0'


# --- merge: component matching (comp already in self → mark build_only if needed) ---

def test_merge_component_matching():
    comp_a = Component(name='prod', suffix='tar.xz', filename='pkg-prod.tar.xz',
                       checksum='aaa', build_only=False)
    comp_b = Component(name='prod', suffix='tar.xz', filename='pkg-prod.tar.xz',
                       checksum='aaa', build_only=True)

    pkg_a = Package(name='pkg')
    pkg_a.components = [comp_a]

    pkg_b = Package(name='pkg')
    pkg_b.components = [comp_b]   # same component but build_only=True

    pkg_a.merge(pkg_b)
    assert pkg_a.components[0].build_only is True


# --- merge: attribute already set → skip (first-wins) ---

def test_merge_args_same_key():
    pkg_a = Package(name='pkg')
    pkg_a.ancestors = ['parent_a']

    pkg_b = Package(name='pkg')
    pkg_b.ancestors = ['parent_b']

    pkg_a.merge(pkg_b)
    # ancestors from pkg_a should be preserved, not overwritten by pkg_b
    assert pkg_a.ancestors == ['parent_a']



