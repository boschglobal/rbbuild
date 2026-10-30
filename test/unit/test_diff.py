#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest

from unittest.mock import MagicMock

from rbbuild.core.runtime_settings import CompareState, DiffMode
from rbbuild.librbb.term import term, ColorSchemeNone
from rbbuild.package.diff import CompareResult, PackageDiff
from rbbuild.package.package import Package


# Force plain text output for all tests in this module
term.color = ColorSchemeNone

_ALL_STATES = list(CompareState)


def _make_pkg(name, version, namespace='', git_hash=None, git_repo=None, dependencies=None):
    pkg = Package(name=name, version=version)
    pkg.namespace = namespace
    pkg.git_hash = git_hash
    pkg.git_repo = git_repo
    if dependencies is not None:
        pkg.dependencies = dependencies
    return pkg


def _diff(filter_changes=None, diffmode=DiffMode.BASIC):
    if filter_changes is None:
        filter_changes = _ALL_STATES
    return PackageDiff(diffmode=diffmode, filter_changes=filter_changes)


# compare(): basic state detection

def test_compare_same():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '1.0.0')
    result = diff.compare(a, b, traverse_deps=True)
    assert result.state == CompareState.SAME
    assert result.pkg_a is a
    assert result.pkg_b is b


def test_compare_changed():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '2.0.0')
    result = diff.compare(a, b, traverse_deps=False)
    assert result.state == CompareState.CHANGED


def test_compare_new():
    diff = _diff()
    b = _make_pkg('nng', '2.0.0')
    result = diff.compare(None, b, traverse_deps=False)
    assert result.state == CompareState.NEW
    assert result.pkg_a is None
    assert result.pkg_b is b


def test_compare_deleted():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    result = diff.compare(a, None, traverse_deps=False)
    assert result.state == CompareState.DELETED
    assert result.pkg_a is a
    assert result.pkg_b is None


def test_compare_moved():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0', namespace='ns_a')
    b = _make_pkg('nng', '2.0.0', namespace='ns_b')
    result = diff.compare(a, b, traverse_deps=False)
    assert result.state == CompareState.MOVED


def test_compare_different_names_raises():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('boost', '1.0.0')
    with pytest.raises(RuntimeError):
        diff.compare(a, b, traverse_deps=False)


def test_compare_both_none_raises():
    diff = _diff()
    with pytest.raises(RuntimeError):
        diff.compare(None, None, traverse_deps=False)


# compare(): dependency traversal

def test_compare_changed_traverses_deps():
    diff = _diff()
    dep_a = _make_pkg('dep', '1.0.0')
    dep_b = _make_pkg('dep', '2.0.0')
    a = _make_pkg('nng', '1.0.0', dependencies={'dep@tc': dep_a})
    b = _make_pkg('nng', '2.0.0', dependencies={'dep@tc': dep_b})
    result = diff.compare(a, b, traverse_deps=True)
    assert result.state == CompareState.CHANGED
    assert len(result.dependencies) == 1
    assert result.dependencies[0].state == CompareState.CHANGED
    assert result.dependencies[0].pkg_a is dep_a
    assert result.dependencies[0].pkg_b is dep_b


def test_compare_changed_new_dep_in_b():
    # a dep present only in pkg_b (newly added) yields a NEW entry
    diff = _diff()
    dep_a = _make_pkg('existing', '1.0.0')
    dep_new = _make_pkg('newdep', '1.0.0')
    a = _make_pkg('nng', '1.0.0', dependencies={'existing@tc': dep_a})
    b = _make_pkg('nng', '2.0.0', dependencies={'existing@tc': dep_a, 'newdep@tc': dep_new})
    result = diff.compare(a, b, traverse_deps=True)
    assert result.state == CompareState.CHANGED
    assert len(result.dependencies) == 2
    new_dep = next(d for d in result.dependencies if d.state == CompareState.NEW)
    assert new_dep.pkg_b is dep_new


@pytest.mark.parametrize('namespace', ['', 'moved'])
@pytest.mark.parametrize('names', [['newdep'], ['newdep', 'other']])
def test_compare_reports_first_dependencies_added_to_package(namespace, names):
    diff = _diff()
    added = {name: _make_pkg(name, '1.0.0') for name in names}
    a = _make_pkg('nng', '1.0.0', dependencies={})
    b = _make_pkg('nng', '2.0.0', namespace=namespace,
                  dependencies=added)

    result = diff.compare(a, b, traverse_deps=True)

    expected_state = CompareState.MOVED if namespace else CompareState.CHANGED
    assert result.state == expected_state
    assert len(result.dependencies) == len(added)
    for child, package in zip(result.dependencies, added.values()):
        assert child.state == CompareState.NEW
        assert child.pkg_a is None
        assert child.pkg_b is package


def test_compare_changed_no_traverse_skips_deps():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0', dependencies={'dep@tc': _make_pkg('dep', '1.0')})
    b = _make_pkg('nng', '2.0.0', dependencies={'dep@tc': _make_pkg('dep', '2.0')})
    result = diff.compare(a, b, traverse_deps=False)
    assert result.state == CompareState.CHANGED
    assert result.dependencies == []


def test_compare_changed_dep_deleted_when_missing_in_b():
    # dependency in pkg_a not present in pkg_b → DELETED dep
    diff = _diff()
    dep_a = _make_pkg('dep', '1.0.0')
    a = _make_pkg('nng', '1.0.0', dependencies={'dep@tc': dep_a})
    b = _make_pkg('nng', '2.0.0', dependencies={})
    result = diff.compare(a, b, traverse_deps=True)
    assert result.state == CompareState.CHANGED
    assert len(result.dependencies) == 1
    assert result.dependencies[0].state == CompareState.DELETED


def test_compare_same_no_dep_traversal():
    # deps are not traversed when state == SAME
    diff = _diff()
    dep_a = _make_pkg('dep', '1.0.0')
    dep_b = _make_pkg('dep', '2.0.0')
    a = _make_pkg('nng', '1.0.0', dependencies={'dep@tc': dep_a})
    b = _make_pkg('nng', '1.0.0', dependencies={'dep@tc': dep_b})
    result = diff.compare(a, b, traverse_deps=True)
    assert result.state == CompareState.SAME
    assert result.dependencies == []


# compare(): CompareResult dataclass

def test_compare_result_fields():
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '2.0.0')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)
    assert result.pkg_a is a
    assert result.pkg_b is b
    assert result.state == CompareState.CHANGED
    assert result.dependencies is None


# _get_compare_state_text(): plain-text verification (no color codes with ColorSchemeNone)

def test_compare_state_text_same():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '1.0.0')
    text = diff._get_compare_state_text(CompareState.SAME, a, b)
    assert 'nng' in text
    assert '1.0.0' in text
    assert 'same' in text


def test_compare_state_text_changed():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '2.0.0')
    text = diff._get_compare_state_text(CompareState.CHANGED, a, b)
    assert 'nng' in text
    assert '1.0.0' in text
    assert '2.0.0' in text
    assert 'changed' in text
    assert '\u2192' in text


def test_compare_state_text_new():
    diff = _diff()
    b = _make_pkg('nng', '2.0.0')
    text = diff._get_compare_state_text(CompareState.NEW, None, b)
    assert 'nng' in text
    assert '2.0.0' in text
    assert 'new' in text


def test_compare_state_text_deleted():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    text = diff._get_compare_state_text(CompareState.DELETED, a, None)
    assert 'nng' in text
    assert '1.0.0' in text
    assert 'deleted' in text


def test_compare_state_text_moved():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0', namespace='ns_a')
    b = _make_pkg('nng', '2.0.0', namespace='ns_b')
    text = diff._get_compare_state_text(CompareState.MOVED, a, b)
    assert 'nng' in text
    assert 'moved' in text


# get_compare_text(): filter and basic mode

def test_get_compare_text_filtered_out():
    diff = PackageDiff(diffmode=DiffMode.BASIC, filter_changes=[CompareState.CHANGED])
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '1.0.0')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.SAME)
    texts = list(diff.get_compare_text(result, scmman=None, issueman=None))
    assert texts == ['']


def test_get_compare_text_same_included():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '1.0.0')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.SAME)
    texts = list(diff.get_compare_text(result, scmman=None, issueman=None))
    assert len(texts) == 1
    assert 'same' in texts[0]


def test_get_compare_text_changed_basic():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '2.0.0')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)
    texts = list(diff.get_compare_text(result, scmman=None, issueman=None))
    assert len(texts) == 1
    assert 'changed' in texts[0]


def test_get_compare_text_new_basic():
    diff = _diff()
    b = _make_pkg('nng', '2.0.0')
    result = CompareResult(pkg_a=None, pkg_b=b, state=CompareState.NEW)
    texts = list(diff.get_compare_text(result, scmman=None, issueman=None))
    assert len(texts) == 1
    assert 'new' in texts[0]


def test_get_compare_text_deleted_basic():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    result = CompareResult(pkg_a=a, pkg_b=None, state=CompareState.DELETED)
    texts = list(diff.get_compare_text(result, scmman=None, issueman=None))
    assert len(texts) == 1
    assert 'deleted' in texts[0]


# get_compare_text(): commits mode calls _git_commits when state is CHANGED

def test_get_compare_text_commits_mode_calls_scm():
    diff = PackageDiff(diffmode=DiffMode.COMMITS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc123', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def456', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['PROJ-1']
    mock_commit.message = 'Fix something'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))
    assert any('PROJ-1' in t for t in texts)
    assert any('Fix something' in t for t in texts)
    mock_scmman.service.assert_called_once_with(url='https://git.example.com/nng')
    mock_service.get_commits.assert_called_once_with(since='abc123', until='def456', limit=diff.max_git_commits)


def test_get_compare_text_commits_mode_no_git_repo():
    # when git_repo is None, _git_commits yields nothing
    diff = PackageDiff(diffmode=DiffMode.COMMITS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc123', git_repo=None)
    b = _make_pkg('nng', '2.0.0', git_hash='def456', git_repo=None)
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)
    texts = list(diff.get_compare_text(result, scmman=MagicMock(), issueman=MagicMock()))
    # only the state text, no commits
    assert len(texts) == 1
    assert 'changed' in texts[0]


def test_get_compare_text_commits_mode_non_changed_state_no_scm():
    # _git_commits only runs when state is CHANGED
    diff = PackageDiff(diffmode=DiffMode.COMMITS, filter_changes=_ALL_STATES)
    b = _make_pkg('nng', '2.0.0')
    result = CompareResult(pkg_a=None, pkg_b=b, state=CompareState.NEW)
    mock_scmman = MagicMock()
    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))
    assert len(texts) == 1
    assert 'new' in texts[0]
    mock_scmman.service.assert_not_called()


def test_get_compare_text_commit_no_jira_keys():
    diff = PackageDiff(diffmode=DiffMode.COMMITS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = []
    mock_commit.message = 'no-ticket change'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))
    assert any('(no ticket)' in t for t in texts)
    assert any('no-ticket change' in t for t in texts)


# A commit referencing more than one JIRA key produces a comma-joined key string.
def test_get_compare_text_commits_mode_multiple_jira_keys():
    diff = PackageDiff(diffmode=DiffMode.COMMITS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['PROJ-1', 'PROJ-2']
    mock_commit.message = 'multi-ticket fix'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))
    combined = ' '.join(texts)
    assert 'PROJ-1' in combined
    assert 'PROJ-2' in combined
    assert 'multi-ticket fix' in combined


# get_compare_text(): DiffMode.GITDETAILS adds commit metadata

# GITDETAILS mode appends commit URL, hash, and committer to the output.
def test_get_compare_text_gitdetails_mode():
    diff = PackageDiff(diffmode=DiffMode.GITDETAILS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc123', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def456', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['PROJ-42']
    mock_commit.message = 'refactor stuff'
    mock_commit.commit_url = 'https://git.example.com/nng/commit/def456'
    mock_commit.git_hash = 'def456'
    mock_commit.author_email = 'dev@example.com'
    mock_commit.author_name = 'Developer'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))
    combined = ' '.join(texts)
    assert 'commit URL' in combined
    assert 'https://git.example.com/nng/commit/def456' in combined
    assert 'git hash' in combined
    assert 'def456' in combined
    assert 'dev@example.com' in combined
    assert 'Developer' in combined


# get_compare_text(): DiffMode.JIRADETAILS

# JIRADETAILS mode fetches JIRA issue details and includes linked tickets.
def test_get_compare_text_jiradetails_with_linked_issues():
    diff = PackageDiff(diffmode=DiffMode.JIRADETAILS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['PROJ-99']
    mock_commit.message = 'fixed linked issue'

    mock_issue = {
        'fields': {
            'issuelinks': [
                {
                    'type': {'inward': 'is blocked by'},
                    'inwardIssue': {'key': 'PROJ-10', 'fields': {'summary': 'blocking bug'}},
                }
            ]
        }
    }
    mock_jira = MagicMock()
    mock_jira.get_issue.return_value = mock_issue
    mock_issueman = MagicMock()
    mock_issueman.service.return_value = mock_jira

    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=mock_issueman))
    combined = ' '.join(texts)
    assert 'PROJ-99' in combined
    assert 'is blocked by' in combined
    assert 'PROJ-10' in combined
    assert 'blocking bug' in combined


# JIRADETAILS raises SyntaxError when a JIRA key has no dash (e.g. just 'PROJ').
def test_get_compare_text_jiradetails_invalid_key_format():
    diff = PackageDiff(diffmode=DiffMode.JIRADETAILS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['INVALIDKEY']  # no dash
    mock_commit.message = 'bad ticket'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    with pytest.raises(SyntaxError, match='Invalid ticket form'):
        list(diff.get_compare_text(result, scmman=mock_scmman, issueman=MagicMock()))


# JIRADETAILS silently ignores a LookupError from an unregistered JIRA project key.
def test_get_compare_text_jiradetails_unknown_project_silently_ignored():
    diff = PackageDiff(diffmode=DiffMode.JIRADETAILS, filter_changes=_ALL_STATES)
    a = _make_pkg('nng', '1.0.0', git_hash='abc', git_repo='https://git.example.com/nng')
    b = _make_pkg('nng', '2.0.0', git_hash='def', git_repo='https://git.example.com/nng')
    result = CompareResult(pkg_a=a, pkg_b=b, state=CompareState.CHANGED)

    mock_commit = MagicMock()
    mock_commit.jira_keys = ['UNKNOWN-42']
    mock_commit.message = 'commit from unknown project'
    mock_service = MagicMock()
    mock_service.get_commits.return_value = iter([mock_commit])
    mock_scmman = MagicMock()
    mock_scmman.service.return_value = mock_service

    mock_issueman = MagicMock()
    mock_issueman.service.side_effect = LookupError('project not found')

    # Must not raise — LookupError from issueman.service is silently ignored
    texts = list(diff.get_compare_text(result, scmman=mock_scmman, issueman=mock_issueman))
    assert any('UNKNOWN-42' in t for t in texts)


# _get_compare_state_text(): unknown state guard

# _get_compare_state_text raises NotImplementedError for an unrecognised state.
def test_compare_state_text_unknown_state_raises():
    diff = _diff()
    a = _make_pkg('nng', '1.0.0')
    b = _make_pkg('nng', '2.0.0')
    # Use an integer to represent a bogus state that doesn't match any CompareState branch
    with pytest.raises(NotImplementedError):
        diff._get_compare_state_text(99, a, b)
