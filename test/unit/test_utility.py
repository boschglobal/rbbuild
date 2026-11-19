# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest

from rbbuild.service.utility import (
    bump_conflict_version, matches_localversion, version_sort_function,
)

# ---------------------------------------------------------------------------
# version_sort_function — sort ordering
# ---------------------------------------------------------------------------

# rbbuild-style 'major.minor.patch-branch.build' versions: build counter wins
def test_sort_rbbuild_versions():
    versions = ['1.2.3-master.4', '1.2.3-master.5', '1.0.0-master.6']
    result = sorted(versions, key=version_sort_function, reverse=True)
    assert result == ['1.2.3-master.5', '1.2.3-master.4', '1.0.0-master.6']


# plain numeric dotted versions
def test_sort_numeric_dotted():
    versions = ['1.2.3.4', '1.0.0.0', '2.0.0.99', '3.1']
    result = sorted(versions, key=version_sort_function, reverse=True)
    assert result == ['3.1', '2.0.0.99', '1.2.3.4', '1.0.0.0']


# '+' separator (e.g. build metadata)
def test_sort_plus_separator():
    versions = ['1.2.3+snapshot', '1.2']
    result = sorted(versions, key=version_sort_function, reverse=True)
    assert result == ['1.2.3+snapshot', '1.2']


# mixed-type segments: must not raise TypeError
def test_sort_mixed_type_no_crash():
    versions = ['any-version-string.99.10', '1.0.custom-version', '2.0a']
    result = sorted(versions, key=version_sort_function, reverse=True)
    assert len(result) == 3   # order is best-effort; the key point is no crash


# ---------------------------------------------------------------------------
# version_sort_function — PEP 508 exact version strings (no '==' prefix;
# repository versions are plain strings, never constraint expressions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('ver', [
    '1.0.0',
    '1.2.3',
    '1.0.0.post1',
    '1.0.0.dev0',
    '1.0.0a1',
    '1.0.0b2',
    '1.0.0rc3',
    '1.0.0+local',
])
def test_sort_key_pep508_versions_no_crash(ver):
    # PEP 508 exact-version strings (the part after '==') must not raise
    result = version_sort_function(ver)
    assert isinstance(result, list)
    assert len(result) > 0


# PEP 508 pre-release ordering: rc > b > a
def test_sort_pep508_prerelease_order():
    versions = ['1.0.0a1', '1.0.0rc1', '1.0.0b1']
    result = sorted(versions, key=version_sort_function, reverse=True)
    # 'rc' > 'b' > 'a' lexicographically → rc > b > a
    assert result == ['1.0.0rc1', '1.0.0b1', '1.0.0a1']


# ---------------------------------------------------------------------------
# matches_localversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('version, localversion, expected', [
    ('1.2.3.4.dev1+rbbuild.1234', 'rbbuild.1234', True),
    ('1.2.3.4.dev1+rbbuild.1234', 'RBBUILD.1234', True),
    ('1.2.3.4.dev1+rbbuild.1234', 'rbbuild-1234', True),
    ('1.2.3.4.dev1+rbbuild.1234', 'rbbuild', False),
    ('1.2.3.4.dev1+rbbuild.1234', 'rbbuild.12', False),
    ('1.2.3.4.dev1+rbbuild.1234', 'rbbuild.*', False),
    ('1.2.3.4', 'rbbuild.1234', False),
    ('1.2.3-master.4', 'rbbuild.1234', False),
])
def test_matches_localversion(version, localversion, expected):
    assert matches_localversion(version, localversion) is expected


# ---------------------------------------------------------------------------
# bump_conflict_version — publish() version-conflict retry
# ---------------------------------------------------------------------------

# A standard 4-part rbbuild version gets a 5th digit appended, starting at 1.
def test_bump_conflict_version_appends_fifth_digit():
    assert bump_conflict_version('1.2.3.4') == '1.2.3.4.1'


# An existing 5th digit is incremented, not reset.
def test_bump_conflict_version_increments_existing_fifth_digit():
    assert bump_conflict_version('1.2.3.4.1') == '1.2.3.4.2'
    assert bump_conflict_version('1.2.3.4.9') == '1.2.3.4.10'


# Development versions (e.g. '<version>.devN+<branch>') keep their dev/local
# suffix intact while the release part is bumped.
def test_bump_conflict_version_preserves_dev_suffix():
    assert bump_conflict_version('1.2.3.4.dev1+mybranch') == '1.2.3.4.1.dev1+mybranch'
    assert bump_conflict_version('1.2.3.4.1.dev1+mybranch') == '1.2.3.4.2.dev1+mybranch'


# Shorter-than-4-part versions are padded with zeros before appending .1
def test_bump_conflict_version_pads_short_versions():
    assert bump_conflict_version('1.2.3') == '1.2.3.0.1'
