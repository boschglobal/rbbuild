#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json
import pytest
import tomllib


def test_empty_project_dir(rbbconf_empty, tmp_path):
    assert len([*rbbconf_empty.workdir.iterdir()]) == 0
    # These commands are part of the default build pipeline and should not
    # fail with an exception or sys.exit(1)
    rbbconf_empty.run(['-g'])

    # default profile — value is repr-formatted (quoted) by getconf
    rbbconf_empty.run(['-g', 'settings.profile'])
    assert rbbconf_empty.read_console().strip() == "[settings]\nprofile = 'standalone'"

    rbbconf_empty.run(['-l', 'profiles'])
    rbbconf_empty.run(['-l', 'toolchains'])
    rbbconf_empty.run(['-l', 'channels'])
    rbbconf_empty.run(['-l', 'services'])
    rbbconf_empty.run(['-l', 'all'])
    rbbconf_l_all_out = rbbconf_empty.read_console()

    rbbconf_empty.run(['-l'])
    rbbconf_l_out = rbbconf_empty.read_console()

    # Ensure that the output of "rbbconf -l" and "rbbconf -l all" are the same
    assert rbbconf_l_out == rbbconf_l_all_out

    # None of the above commands should have created any files, e.g., obj or staging folders
    assert len([*rbbconf_empty.workdir.iterdir()]) == 0


def test_default_project_dir(rbbconf, tmp_path):
    # active profile — value is repr-formatted (quoted) by getconf
    rbbconf.run(['-g', 'settings.profile', '-P', 'test'])
    assert rbbconf.read_console().strip() == "[settings]\nprofile = 'test'"

    rbbconf.run(['-l', 'profiles'])
    assert '*test' in rbbconf.read_console()

    # fake_artifactory service (from the builtin test profile)
    rbbconf.run(['-l', 'services'])
    cons_out = rbbconf.read_console()
    assert 'fake_artifactory' in cons_out
    for line in cons_out.split('\n'):
        if line.strip().startswith('fake_artifactory'):
            sname, stype, url = line.split(maxsplit=2)
            assert sname == 'fake_artifactory'
            assert stype == 'local_file_service'
            assert url.startswith('file:')
            assert '/share/rbbuild/config/../../../test/data' in url.replace('\\', '/')

    # sample-development channel (from the builtin test profile)
    rbbconf.run(['-l', 'channels'])
    cons_out = rbbconf.read_console()
    assert 'sample-development' in cons_out
    for line in cons_out.split('\n'):
        if line.startswith('sample-development'):
            parts = line.split()
            assert parts[0] == 'sample-development'
            assert parts[1] == 'rbbuild'
            assert parts[2] == 'fake_artifactory'
            assert parts[3] == 'sample-development-local'
            assert parts[4] == 'components'


def test_list_profiles_origin_attributes(rbbconf, tmp_path, monkeypatch):
    import rbbuild.container.configuration as configuration

    root = tmp_path / 'plugin_root'
    (root / 'profiles' / 'plug').mkdir(parents=True)
    (root / 'profiles' / 'plug' / 'plug.toml').write_text('')
    monkeypatch.setattr(configuration, 'load_config_roots', lambda: [root])
    user_profile = rbbconf.user_home / '.config/rbbuild/profiles/usr'
    user_profile.mkdir(parents=True)
    (user_profile / 'usr.toml').write_text('')

    rbbconf.run(['-l', 'profiles'])
    attrs = {}
    for line in rbbconf.read_console().split('\n'):
        tokens = line.split()
        if line.startswith('['):
            attrs[tokens[1].lstrip('*')] = tokens[-1]
    assert attrs['plug'] == 'plugin'
    assert attrs['standalone'] == 'builtin'
    assert attrs['test'] == 'builtin'
    assert attrs['usr'] == 'user'


# --- getconf filter tests ---

# getconf with a simple key name filter shows only entries with that key.
def test_getconf_key_filter(rbbconf):
    rbbconf.run(['-g', 'settings.default_channel'])
    out = rbbconf.read_console()
    # Default channel from test profile [settings]
    assert 'example-development' in out


# getconf with a section.key filter shows entries for a specific service.
def test_getconf_section_filter(rbbconf):
    rbbconf.run(['-g', 'profile.services.fake_artifactory'])
    out = rbbconf.read_console()
    assert 'fake_artifactory' in out
    assert 'local_file_service' in out
    # Other services must not appear
    assert 'fossid_service' not in out
    assert 'jira_service' not in out


# getconf with a wildcard section filter shows all matching sub-sections.
def test_getconf_wildcard_section(rbbconf):
    rbbconf.run(['-g', 'profile.channels.*'])
    out = rbbconf.read_console()
    # Both rbbuild-type channels from the test profile should appear
    assert 'example-development' in out
    assert 'example-stable' in out


# getconf with '.url' key filter shows every 'url' entry across all sections.
def test_getconf_url_filter(rbbconf):
    rbbconf.run(['-g', 'profile.services.*.url'])
    out = rbbconf.read_console()
    # fossid_service URL (defined in test user profile)
    assert 'https://fossid.example.com/15/' in out
    # jira_service URL
    assert 'https://jira.example.com/tracker/' in out


# getconf with JSON output
def test_getconf_json_output(rbbconf):
    rbbconf.run(['-g', 'settings', '--format=json'])
    out = rbbconf.read_console()
    data = json.loads(out)
    assert data['settings']['profile'] == 'test'


# --- setconf tests ---

# setconf stores a settings key in the user rbbuild.toml and reports it.
def test_setconf_simple_key(rbbconf_empty, user_home_empty):
    rbbconf_empty.run(['-s', 'toolchain-linux=yocto-armhf-4.0'])
    out = rbbconf_empty.read_console()
    assert 'toolchain-linux' in out
    assert 'yocto-armhf-4.0' in out

    # Verify the value was written to the user config file
    config_file = user_home_empty / '.config/rbbuild/rbbuild.toml'
    assert config_file.exists()
    with open(config_file, 'rb') as fd:
        saved = tomllib.load(fd)
    assert saved['settings']['toolchain-linux'] == 'linux-yocto-armhf-4.0'


# All spellings of a default toolchain are stored as settings.toolchain-<platform> = <platform>-<tcid>
@pytest.mark.parametrize('setting', [
    'toolchain-linux=linux-yocto-armhf-4.0',
    'toolchain-linux=yocto-armhf-4.0',
    'toolchain=linux-yocto-armhf-4.0',
    'toolchain=yocto-armhf-4.0',
])
def test_setconf_default_toolchain_is_canonical(rbbconf_empty, user_home_empty, setting):
    rbbconf_empty.run(['--platform', 'linux', '-s', setting])

    with open(user_home_empty / '.config/rbbuild/rbbuild.toml', 'rb') as fd:
        saved = tomllib.load(fd)
    assert saved['settings'] == {'toolchain-linux': 'linux-yocto-armhf-4.0'}


# setconf with a multi-part dotted key writes into the correct TOML section.
def test_setconf_dotted_key(rbbconf_empty, user_home_empty):
    rbbconf_empty.run(['-s', 'profile.services.artifactory_service.url=https://example.com/'])
    config_file = user_home_empty / '.config/rbbuild/rbbuild.toml'
    with open(config_file, 'rb') as fd:
        saved = tomllib.load(fd)
    assert saved['profile']['services']['artifactory_service']['url'] == 'https://example.com/'


# credentials are masked in setconf output but stored verbatim in the user config.
def test_setconf_credentials_masked(rbbconf_empty, user_home_empty):
    rbbconf_empty.run(['-s', 'profile.services.fake_artifactory.credentials=MY_SECRET_KEY'])
    out = rbbconf_empty.read_console()
    assert 'MY_SECRET_KEY' not in out
    assert '********' in out

    config_file = user_home_empty / '.config/rbbuild/rbbuild.toml'
    with open(config_file, 'rb') as fd:
        saved = tomllib.load(fd)
    assert saved['profile']['services']['fake_artifactory']['credentials'] == 'MY_SECRET_KEY'


# setconf accepts multiple comma-separated key=value pairs in a single call.
def test_setconf_multiple_keys(rbbconf_empty, user_home_empty):
    rbbconf_empty.run(['-s', 'toolchain-linux=linux-yocto,toolchain-win32=win32-vs2022'])
    out = rbbconf_empty.read_console()
    assert 'linux-yocto' in out
    assert 'win32-vs2022' in out

    config_file = user_home_empty / '.config/rbbuild/rbbuild.toml'
    with open(config_file, 'rb') as fd:
        saved = tomllib.load(fd)
    assert saved['settings']['toolchain-linux'] == 'linux-yocto'
    assert saved['settings']['toolchain-win32'] == 'win32-vs2022'


# setconf with a value that contains no '=' raises SyntaxError.
def test_setconf_invalid_syntax(rbbconf_empty):
    with pytest.raises(SyntaxError):
        rbbconf_empty.run(['-s', 'no_equals_sign'])


# --- list content tests ---

# list toolchains shows platform, tcid and cmake file path for the test profile.
def test_list_toolchains_content(rbbconf):
    rbbconf.run(['-l', 'toolchains'])
    out = rbbconf.read_console()
    assert 'linux' in out
    assert 'native' in out
    assert 'win32' in out
    assert 'mingw' in out
    assert 'linux-native.cmake' in out


# list channels shows all channel details for the test profile.
def test_list_channels_test_profile(rbbconf):
    rbbconf.run(['-l', 'channels'])
    out = rbbconf.read_console()
    assert 'example-development' in out
    for line in out.split('\n'):
        if line.startswith('example-development'):
            parts = line.split()
            assert parts[0] == 'example-development'
            assert parts[1] == 'rbbuild'
            assert parts[2] == 'fake_artifactory'
            assert parts[3] == 'example-development-local'
            assert parts[4] == 'components'
            break


# list services shows all three remote services configured in the test profile.
def test_list_services_test_profile(rbbconf):
    rbbconf.run(['-l', 'services'])
    out = rbbconf.read_console()
    assert 'fake_artifactory' in out
    assert 'fossid_service' in out
    assert 'jira_service' in out


# --- list: invalid target ---

# rbbconf -l with an unrecognised category raises SyntaxError.
def test_list_invalid_target(rbbconf_empty):
    with pytest.raises(SyntaxError, match='Invalid argument'):
        rbbconf_empty.run(['-l', 'foobar'])

