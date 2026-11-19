# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest

from rbbuild.deps.converter import deps_json_to_config
from rbbuild.package.package import Package


@pytest.fixture
def deps_parser(app):
    yield app.deps.parser()


def check_component_defaults(pkg: Package):
    assert pkg.components == []



@pytest.mark.parametrize( 'deps_entry, expected_version',
                          [
                              ('sample_pkg-1.0.99-master.4', '1.0.99-master.4'),
                          ]
                        )
def test_rbbuild_version(deps_parser, deps_entry, expected_version):
    pkg = deps_parser.parse_item(deps_entry)

    # Defined in deps.json
    assert pkg.name == 'sample_pkg'
    assert pkg.version == expected_version
    # Defaults (pkg) - channel and toolchain are None until resolved by RepositoryManager
    assert pkg.installdir == ''
    assert pkg.channel is None
    assert pkg.toolchain is None
    assert pkg.components == []
    # Defaults (Component)
    check_component_defaults(pkg)


@pytest.mark.parametrize( 'deps_config, ns_pkgs',
                          [
                              (
                                [{'deps': ['sample_pkg-1.0.99-master.4'], 'namespace': 'some_namespace'}],
                                ['some_namespace/sample_pkg-1.0.99-master.4']
                              ),
                              (
                                [
                                  {'deps': ['sample_pkg-1.0.99-master.4'], 'namespace': 'some_namespace'},
                                  {'deps': ['sample_pkg-1.0.99-master.4'], 'namespace': 'other_namespace'},
                                ],
                                [
                                    'some_namespace/sample_pkg-1.0.99-master.4',
                                    'other_namespace/sample_pkg-1.0.99-master.4'
                                ]
                              ),
                              (
                                [
                                  {'deps': ['sample_pkg-1.0.99-master.4', 'anotherpkg-0.1.2-develop.8'], 'namespace': 'some_namespace'},
                                  {'deps': ['sample_pkg-1.0.99-master.4', 'anotherpkg-0.1.2-develop.8'], 'namespace': 'other_namespace'},
                                ],
                                [
                                    'some_namespace/sample_pkg-1.0.99-master.4',
                                    'some_namespace/anotherpkg-0.1.2-develop.8',
                                    'other_namespace/sample_pkg-1.0.99-master.4',
                                    'other_namespace/anotherpkg-0.1.2-develop.8'
                                ]
                              )
                          ]
                        )
def test_deps_parse_namespaces(deps_parser, deps_config, ns_pkgs):
    npkgs = 0
    for pkg_items, attrs in deps_parser.walk(deps_config):
        npkgs += len(pkg_items)
        for item in pkg_items:
            pkg = deps_parser.parse_item(item, attrs)
            assert f'{pkg.namespace}/{str(pkg)}' in ns_pkgs
            assert pkg.channel is None
            assert pkg.components == []

            check_component_defaults(pkg)

    assert npkgs == len(ns_pkgs)


@pytest.mark.parametrize(
    'deps_config, attrs_list',
    [
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 build_only']}],
            [(None, None, 'build_only', True)],
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 build_only traverse=0']}],
            [
                (None, None, 'build_only', True),
                (None, None, 'traverse', False),
            ]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 build_only no_traverse']}],
            [
                (None, None, 'build_only', True),
                (None, None, 'traverse', False),
            ]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 no_traverse=0']}],
            [(None, None, 'traverse', True)]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 build_only']}],
            [(None, None, 'traverse', True)]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 traverse=0 no_traverse']}],
            [(None, None, 'traverse', False)]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 build_only=False build_only=True']}],
            [
                (None, None, 'build_only', True)
            ]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 suffixes=rpm,tar.xz']}],
            [
                (None, 'rpm', None, True),
                (None, 'tar.xz', None, True)
            ]
        ),
        (
            [{'deps': ['sample_pkg-1.0.99-master.4 suffixes=rpm'], 'build_only': 'True'}],
            [
                (None, 'rpm', 'build_only', True)
            ]
        ),
        (
            [{'deps': ['anotherpkg build_only=False'], 'build_only': 'True'}],
            [
                (None, None, 'build_only', False)
            ]
        ),
        (
            [{'deps': ['anotherpkg component=dev build_only=False'], 'build_only': 'True'}],
            [
                ('dev', None, 'build_only', False)
            ]
        ),
        (
            [{'deps': ['anotherpkg components=dev,runtime suffixes=rpm,tar.xz traverse=0'], 'build_only': 'True'}],
            [
                ('dev',     'rpm', 'build_only', True),
                ('runtime', 'rpm', 'build_only', True),
                ('dev',     'rpm', 'traverse', False),
                ('runtime', 'rpm', 'traverse', False),
            ]
        ),
        (
            [{'deps': ['anotherpkg'], 'traverse': False}],
            [(None, None, 'traverse', False)]
        ),
        (
            [{'deps': ['anotherpkg'], 'no_traverse': 'True'}],
            [(None, None, 'traverse', False)]
        ),
        (
            [{'deps': ['anotherpkg traverse'], 'traverse': False}],
            [(None, None, 'traverse', True)]
        ),
    ]
)
def test_deps_parse_attributes(deps_parser, deps_config, attrs_list):
    for pkg_items, attrs in deps_parser.walk(deps_config):
        for item in pkg_items:
            pkg = deps_parser.parse_item(item, attrs)

            for comp, sfx, key, value in attrs_list:
                # assert(getattr(pkg, key) == value)
                assert pkg.component_specifier.check(comp, sfx, key) == value


@pytest.mark.parametrize(
    'item',
    [
        'sample_pkg-1.0 traverse=1 no_traverse',
        'sample_pkg-1.0 traverse=0 no_traverse=0',
    ]
)
def test_deps_parse_traverse_contradiction(deps_parser, item):
    with pytest.raises(SyntaxError):
        deps_parser.parse_item(item, {})


# Note that this test is supposed to run on Windows and Linux.
# For this reason, we are defining separate expected values.
@pytest.mark.parametrize( 'deps_config, pkgs',
                          [
                              (
                                [
                                    {'deps': ['sample_pkg-1.0.99-master.4'], 'restrict_platform': 'linux'},
                                    {'deps': ['anotherpkg-0.1.2-develop.8'], 'restrict_platform': 'win32'},
                                ],
                                [ 'sample_pkg-1.0.99-master.4',
                                  'anotherpkg-0.1.2-develop.8' ],
                              ),
                              (
                                [{'deps': ['sample_pkg-1.0.99-master.4', 'anotherpkg-0.1.2-develop.8'], 'restrict_platform': 'linux'}],
                                [ 'sample_pkg-1.0.99-master.4',
                                  'anotherpkg-0.1.2-develop.8'],
                              ),
                              (
                                [
                                    {'deps': ['sample_pkg-1.0.99-master.4']},
                                    {'deps': ['anotherpkg-0.1.2-develop.8'], 'restrict_platform': 'linux'},
                                ],
                                [ 'sample_pkg-1.0.99-master.4',
                                  'anotherpkg-0.1.2-develop.8'],
                              ),
                              (
                                [
                                    {'deps': ['sample_pkg-1.0.99-master.4'], 'restrict_toolchain': 'native'},
                                    {'deps': ['anotherpkg-0.1.2-develop.8']},
                                ],
                                [ 'sample_pkg-1.0.99-master.4',
                                  'anotherpkg-0.1.2-develop.8' ],
                              ),
                          ]
                        )
def test_deps_parse_platform(deps_parser, deps_config, pkgs):
    for pkg_items, attrs in deps_parser.walk(deps_config):
        for item in pkg_items:
            pkg = deps_parser.parse_item(item, attrs)

            pkgstr = pkg.name + '-' + pkg.version
            assert pkgstr == str(pkg)
            assert pkgstr in pkgs

            # Defaults (pkg) - channel is None until resolved by RepositoryManager
            assert pkg.channel is None
            assert pkg.components == []


@pytest.mark.parametrize( 'deps_config, packages_exp',
                          [
                              (
                                [{'deps': ['sample-sources:fossidsdk_python-master_70ce0e51668']}],
                                [
                                    (
                                           'fossidsdk_python@master_70ce0e51668',
                                           'sample-sources',
                                    )
                                ],
                              ),
                              (
                                [{'deps': [
                                    'sample-sources:sonar_build_wrapper-6.7-linux-x86',
                                    'sample-sources:sonar_build_wrapper-6.7-win-x86',
                                    'sample-sources:sonar_scanner-4.7.0.2747',
                                  ], 'namespace': 'sonar'}],
                                [
                                    (
                                        'sonar_build_wrapper@6.7-linux-x86',
                                        'sample-sources',
                                    ),
                                    (
                                        'sonar_build_wrapper@6.7-win32-x86',
                                        'sample-sources',
                                    ),
                                    (
                                        'sonar_scanner@4.7.0.2747',
                                        'sample-sources',
                                    ),
                                ],
                              ),
                          ]
                        )
def test_deps_plain_entries(deps_parser, deps_config, packages_exp):
    for pkg_items, attrs in deps_parser.walk(deps_config):
        for i, item in enumerate(pkg_items):
            pkg = deps_parser.parse_item(item, attrs)
            pkg_exp = packages_exp[i]
            assert pkg.channel.name == pkg_exp[1]
            assert pkg.toolchain is None


@pytest.mark.parametrize( 'item, name, version, suffix, url',
                          [
                              (
                                  'http://google.com/index.html name=google_index version=1.0 suffix=html',
                                  'google_index', '1.0', 'html', 'http://google.com/index.html',
                              ),
                              (
                                   'https://www.zlib.net/current/zlib.tar.gz version=1.3.1',
                                   'zlib',  '1.3.1', 'tar.gz', 'https://www.zlib.net/current/zlib.tar.gz',
                              ),
                              (
                                   'pkg:generic/index@1.0?download_url=http://google.com/index.html',
                                   'index', '1.0', 'html', 'http://google.com/index.html',
                              ),
                              (
                                   'pkg:generic/zlib@1.3.1?download_url=https://www.zlib.net/current/zlib.tar.gz',
                                   'zlib',  '1.3.1', 'tar.gz', 'https://www.zlib.net/current/zlib.tar.gz',
                              ),
                          ]
                        )
def test_deps_url_entries(deps_parser, item, name, version, suffix, url):
    pkg = deps_parser.parse_item(item, None)

    assert pkg.name    == name
    assert pkg.version == version
    assert pkg.component_specifier.check(name, suffix, None)
    assert pkg.channel  is not None
    assert pkg.channel.name == 'url'
    assert pkg.toolchain is None


# @pytest.mark.skip(reason='parse_deps_range needs reimplementation')
@pytest.mark.parametrize( 'line, pkgstr_a_exp, pkgstr_b_exp',
                          [
                              # rbbuild regular syntax
                              ('nng-1.2.3-master.4..5',               'nng-1.2.3-master.4', 'nng-1.2.3-master.5'),
                              ('nng-1.2.3-master.4..develop.5',       'nng-1.2.3-master.4', 'nng-1.2.3-develop.5'),
                              ('nng-1.2.3-master.4..2.3.4-develop.5', 'nng-1.2.3-master.4', 'nng-2.3.4-develop.5'),
                              # with channel prefix
                              ('sample-development:nng-1.2.3-master.4..5',               'sample-development:nng-1.2.3-master.4', 'sample-development:nng-1.2.3-master.5'),
                              ('sample-development:nng-1.2.3-master.4..develop.5',       'sample-development:nng-1.2.3-master.4', 'sample-development:nng-1.2.3-develop.5'),
                              ('sample-development:nng-1.2.3-master.4..2.3.4-develop.5', 'sample-development:nng-1.2.3-master.4', 'sample-development:nng-2.3.4-develop.5'),
                              # not supported anymore
                              # ('sample-development:nng-1.2.3-master.4..sample-testing:nng-2.3.4-develop.5', 'sample-development:nng-1.2.3-master.4', 'sample-testing:nng-2.3.4-develop.5'),
                              # new syntax
                              ('pkg-1.2.3.4..2.3.4.5',                'pkg-1.2.3.4', 'pkg-2.3.4.5'),
                              ('pkg==1.0..~=1.2',                     'pkg==1.0',    'pkg~=1.2'),
                              ('pkg==1.0..1.2',                       'pkg==1.0',    'pkg==1.2'),
                              ('pkg==1.0..pkg==1.2',                  'pkg==1.0',    'pkg==1.2'),
                              ('pkg[master]==1.0..pkg[hotfix]==1.2',  'pkg[master]==1.0',    'pkg[hotfix]==1.2'),
                              # more complex cases (reported errors)
                              ('mypkg-9.2.2396-REL_9_2.6..9.2.1858-hotfix_v21_1_1.3', 'mypkg-9.2.2396-REL_9_2.6', 'mypkg-9.2.1858-hotfix_v21_1_1.3'),
                              # mixed legacy (branch-based) / normal (plain M.m.b.B) versions
                              ('rbbuild-5.9.2903-develop.262..6.0.3014.0',    'rbbuild-5.9.2903-develop.262', 'rbbuild-6.0.3014.0'),
                              ('rbbuild-6.0.3014.0..5.9.2903-develop.262',    'rbbuild-6.0.3014.0',           'rbbuild-5.9.2903-develop.262'),
                              # plain M.m.b.B rhs with a 5th "conflict" digit (bump_conflict_version())
                              ('rbbuild-5.9.2903-develop.262..6.0.3014.0.1',  'rbbuild-5.9.2903-develop.262', 'rbbuild-6.0.3014.0.1'),
                          ]
                        )
def test_parse_deps_range(deps_parser, line, pkgstr_a_exp, pkgstr_b_exp):
    pkgstr_a, pkgstr_b = deps_parser.parse_deps_range(line)
    assert pkgstr_a == pkgstr_a_exp
    assert pkgstr_b == pkgstr_b_exp


# Invalid input strings
@pytest.mark.parametrize( 'line',
                          [
                              ('nng-1.2.3-master.4...'),
                              ('nng-1.2.3-master.4...5'),
                              ('nng-1.2.3-master.4..master'),
                              ('nng-1.2.3-master.4..example-testing:2.3.4-develop.5'),
                          ]
                        )
def test_parse_deps_range_invalid(deps_parser, line):
    with pytest.raises(SyntaxError):
        pkgstr_a, pkgstr_b = deps_parser.parse_deps_range(line)


@pytest.mark.parametrize( 'deps_entry, expected_fields',
                          [
                              # input string                                                                 channel              pkgname         version          toolchain     components
                              ('pkg:rbbuild/sample_pkg',                                             ['example-development', 'sample_pkg', None,      'linux-native', None]),
                              ('pkg:rbbuild/sample_pkg@1.0.0.0',                                     ['example-development', 'sample_pkg', '1.0.0.0', 'linux-native', None]),
                              ('pkg:rbbuild/sample_pkg@1.0',                                         ['example-development', 'sample_pkg', '1.0',     'linux-native', None]),
                              # With namespace
                              ('pkg:rbbuild/sample_pkg?channel=rbbuild-test',                        ['rbbuild-test',          'sample_pkg', None,      'linux-native', None]),
                              ('pkg:rbbuild/sample_pkg@1.2.3.4?channel=rbbuild-test',                ['rbbuild-test',          'sample_pkg', '1.2.3.4', 'linux-native', None]),
                              # With toolchain
                              ('pkg:rbbuild/sample_pkg?toolchain=win32-mingw',                       ['example-development', 'sample_pkg',  None,     'win32-mingw',   None]),
                              ('pkg:rbbuild/sample_pkg?toolchain=win32-mingw&components=bla,blubb',  ['example-development', 'sample_pkg',  None,     'win32-mingw',   ['bla', 'blubb']]),
                              # Extended namespaces
                              ('pkg:rbbuild/example/sample_pkg@1.1.2.3',                           ['example-development', 'sample_pkg', '1.1.2.3', 'linux-native', None]),
                              ('pkg:rbbuild/example/sample_pkg@1.2.3.4?components=blubb',          ['example-development', 'sample_pkg', '1.2.3.4', 'linux-native', ['blubb']]),
                          ]
                        )
def test_packageurl(deps_parser, deps_entry, expected_fields):
    exp_chname, exp_pkgname, exp_version, exp_toolchain, exp_components = expected_fields

    pkg = deps_parser.parse_item(deps_entry, None)

    assert pkg.name == exp_pkgname
    assert pkg.version == exp_version
    assert pkg.channel.name == exp_chname
    assert str(pkg.toolchain) == exp_toolchain
    if exp_components:
        for comp in exp_components:
            assert pkg.component_specifier.check(comp, None, None)


@pytest.mark.skip(reason='Feature currently not supported')
def test_expand_variables_line(deps_parser):
    pkg = deps_parser.parse_item('mypkg-$PACKAGE_VERSION')
    assert pkg.name == 'mypkg'

    pkg = deps_parser.parse_item('mypkg_$PACKAGE_NAME')
    assert pkg.name.startswith('mypkg_test_expand_variables_line')


def test_ignore_comments(deps_parser):
    pkg = deps_parser.parse_item('# boost::master')
    assert pkg is None

    pkg = deps_parser.parse_item('# some comment with another # in the string')
    assert pkg is None

    pkg = deps_parser.parse_item('deps_ends_with_hash #')
    assert pkg.name == 'deps_ends_with_hash'

    pkg = deps_parser.parse_item('deps_ends_with_hash#')
    assert pkg.name == 'deps_ends_with_hash'

    pkg = deps_parser.parse_item('http://example.com/app#url_part version=1.0')
    assert pkg.name == 'app'
    assert pkg.url == 'http://example.com/app#url_part'

    pkg = deps_parser.parse_item('boost==1.2 # random_key=random_value123')
    assert pkg.name == 'boost'
    assert pkg.version == '1.2'
    assert pkg.version_constraints is None


def test_localversion_attribute(deps_parser):
    pkg = deps_parser.parse_item('mypkg>1.0 localversion=rbbuild.1234')
    assert pkg.name == 'mypkg'
    assert pkg.localversion == 'rbbuild.1234'
    assert '1.5' in pkg.version_constraints


def test_localversion_attribute_default(deps_parser):
    assert deps_parser.parse_item('mypkg').localversion is None


def test_localversion_attribute_dict_entry(deps_parser):
    pkg = deps_parser.parse_item({'entry': 'mypkg', 'localversion': 'rbbuild.1234'})
    assert pkg.localversion == 'rbbuild.1234'


# --- walk(): error handling ---

# deps_json_to_config() raises SyntaxError when a section key does not start with '/'.
def test_walk_non_slash_section_key_raises(deps_parser):
    bad_deps = {'not_a_slash': {'deps': ['sample_pkg-1.0.0']}}
    with pytest.raises(SyntaxError, match='not recognized'):
        deps_json_to_config(bad_deps)


# deps_json_to_config() raises SyntaxError when a section attribute duplicates a built-in key.
def test_walk_duplicate_section_attribute_raises(deps_parser):
    # 'installdir' is set automatically from the section path; re-declaring it is an error.
    bad_deps = {'/some_namespace': {'installdir': 'overridden', 'deps': ['sample_pkg-1.0.0']}}
    with pytest.raises(SyntaxError, match='duplicate attribute'):
        deps_json_to_config(bad_deps)


# --- parse_attrs() / parse_item(): edge-case inputs ---

# parse_item with an empty or whitespace-only string returns None.
def test_parse_item_empty_string_returns_none(deps_parser):
    assert deps_parser.parse_item('') is None
    assert deps_parser.parse_item('   ') is None


# A 'name@' entry (trailing at-sign) routes through the '-' branch and strips the '@'.
def test_parse_item_trailing_at_no_version(deps_parser):
    # 'my-package@' has '-' so it enters the elif branch, strips '@', then splits on '-'
    pkg = deps_parser.parse_item('my-package@')
    assert pkg is not None
    # name is split at the first '-': 'my', version is the rest: 'package'
    assert pkg.name == 'my-package'
    assert pkg.version is None


# A 'pkgname@' entry with no dash routes through the else/PEP-508 branch.
def test_parse_item_no_dash_trailing_at(deps_parser):
    # 'mypackage@' has no '-', enters else branch, strips '@', parses as PEP-508 name
    pkg = deps_parser.parse_item('mypackage@')
    assert pkg is not None
    assert pkg.name == 'mypackage'
    assert pkg.version is None


# It is also allowed to have 'spaces in package name@'
def test_parse_item_spaces_in_package_name_no_version(deps_parser):
    pkg = deps_parser.parse_item('my package@')
    assert pkg is not None
    assert pkg.name == 'my package'
    assert pkg.version is None


def test_parse_item_spaces_in_package_name_with_version(deps_parser):
    pkg = deps_parser.parse_item('my package@1.2.3.4')
    assert pkg is not None
    assert pkg.name == 'my package'
    assert pkg.version == '1.2.3.4'


def test_parse_item_spaces_and_dashes_in_package_name(deps_parser):
    pkg = deps_parser.parse_item('my package - with dash@1.2.3.4')
    assert pkg is not None
    assert pkg.name == 'my package - with dash'
    assert pkg.version == '1.2.3.4'


# A 'my-package@1.2.3' entry correctly uses the '@' as name/version separator.
def test_parse_item_dash_pkg_with_at_version(deps_parser):
    pkg = deps_parser.parse_item('my-package@1.2.3')
    assert pkg.name == 'my-package'
    assert pkg.version == '1.2.3'


# An attribute that maps to a Package field via hasattr is set correctly.
def test_parse_item_generic_attr_via_hasattr(deps_parser):
    # 'git_repo' is a Package field; passing it as an attr should set pkg.git_repo
    pkg = deps_parser.parse_item('sample_pkg-1.0.0 git_repo=https://example.com/repo')
    assert pkg.name == 'sample_pkg'
    assert pkg.git_repo == 'https://example.com/repo'


# An attribute that is not a valid Package field raises SyntaxError.
def test_parse_item_unknown_attr_raises(deps_parser):
    with pytest.raises(SyntaxError, match='Invalid package attribute'):
        deps_parser.parse_item('sample_pkg-1.0.0 totally_unknown_attr=value')


# PEP 508 extras branch AND explicit branch= attribute together raise SyntaxError.
def test_parse_item_branch_conflict_raises(deps_parser):
    with pytest.raises(SyntaxError, match='Conflicting specification of branch'):
        deps_parser.parse_item('mypkg[mybranch]==1.0.0 branch=otherbranch')


# prefix channel together with explicit channel= attribute together raise SyntaxError.
def test_parse_item_channel_conflict_raises(deps_parser):
    with pytest.raises(SyntaxError, match='Conflicting specification of channel'):
        deps_parser.parse_item('mychannel:mypkg-1.0.0 channel=otherchannel')


# --- parse_deps_range(): _parse_deps_range_legacy error path ---

# _parse_deps_range_legacy raises SyntaxError for an rhs that matches no pattern.
def test_parse_deps_range_legacy_invalid_rhs(deps_parser):
    with pytest.raises(SyntaxError, match='Invalid version input'):
        deps_parser.parse_deps_range('nng-1.2.3-master.4..!!invalid!!')

