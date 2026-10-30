# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from typing import List, Iterator
from dataclasses import dataclass

from rbbuild.core.runtime_settings import CompareState, DiffMode
from rbbuild.librbb.term import term
from rbbuild.service.issuetracker.issuetracker_manager import IssueTrackerManager
from rbbuild.service.scm.git_repository import GitCommit
from rbbuild.service.scm.manager import SCMManager
from rbbuild.package.package import Package


@dataclass
class CompareResult:
    pkg_a: Package
    pkg_b: Package
    state: CompareState
    dependencies: List['CompareResult'] = None


class PackageDiff:
    def __init__(
        self,
        diffmode: DiffMode,
        filter_changes: List[CompareState],
    ):
        self.allowed_filter = filter_changes
        self.diffmode = diffmode


    @property
    def max_git_commits(self) -> int:
        return 10000


    def compare(
        self,
        pkg_a: Package,
        pkg_b: Package,
        traverse_deps: bool,
    ) -> CompareResult:
        cmp_res = CompareResult(pkg_a, pkg_b, CompareState.SAME, [])

        if not pkg_a and not pkg_b:
            raise RuntimeError('Invalid arguments!')
        elif not pkg_a:
            cmp_res.state = CompareState.NEW
        elif not pkg_b:
            cmp_res.state = CompareState.DELETED
        elif pkg_a.name != pkg_b.name:
            raise RuntimeError(f'Cannot compare different packages {pkg_a.name} {pkg_b.name}')
        elif pkg_a.version != pkg_b.version:
            if pkg_a.namespace == pkg_b.namespace:
                cmp_res.state = CompareState.CHANGED
            else:
                # Same package and branch, different namespace
                cmp_res.state = CompareState.MOVED

            # Only traverse dependencies if we're in CHANGED or MOVED state
            if traverse_deps:
                cmp_res.dependencies = []
                for pkgid, pkg_a_dep in pkg_a.dependencies.items():
                    pkg_b_dep = None
                    if pkg_b.dependencies:
                        pkg_b_dep = pkg_b.dependencies.get(pkgid)
                    cmp_res.dependencies.append(self.compare(pkg_a_dep, pkg_b_dep, True))

                # newly added dependencies
                for pkgid, pkg_b_dep in pkg_b.dependencies.items():
                    found_pkg_b = False
                    for cmp_res_dep in cmp_res.dependencies:
                        if repr(pkg_b_dep) == repr(cmp_res_dep.pkg_a):
                            found_pkg_b = True

                    if not found_pkg_b:
                        cmp_res.dependencies.append(self.compare(None, pkg_b_dep, True))

        return cmp_res


    def _get_compare_state_text(self, state: CompareState, pkg_a: Package, pkg_b: Package) -> str:
        if state == CompareState.SAME:
            return '%s: %s [%s]' % ( term.bright_white(pkg_a.name),
                                     pkg_a.version,
                                     term.cyan('same'))
        elif state == CompareState.CHANGED:
            return '%s: %s %s %s [%s]' % ( term.bright_white(pkg_a.name),
                                           pkg_a.version,
                                           term.bright_white('\u2192'),
                                           pkg_b.version,
                                           term.blue('changed') )
        elif state == CompareState.NEW:
            return '%s %s [%s]' % ( term.bright_white(pkg_b.name),
                                    pkg_b.version,
                                    term.green('new') )
        elif state == CompareState.DELETED:
            return '%s: %s [%s]' % ( term.bright_white(pkg_a.name),
                                     pkg_a.version,
                                     term.red('deleted'))
        elif state == CompareState.MOVED:
            return '%s: %s [%s]' % ( term.bright_white(pkg_b.name),
                                     pkg_b.version,
                                     term.cyan('moved'))

        raise NotImplementedError(f'Unknown compare state {state}')


    def get_compare_text(
        self,
        cmp_res: CompareResult,
        scmman: SCMManager,
        issueman: IssueTrackerManager,
    ) -> Iterator[str]:
        text = ''
        if cmp_res.state not in self.allowed_filter:
            yield text
            return

        text = self._get_compare_state_text(cmp_res.state, cmp_res.pkg_a, cmp_res.pkg_b)
        yield text

        if self.diffmode > 0:
            for commit in self._git_commits(cmp_res, scmman):
                jira_key_string = ''
                jira_link_text = ''
                for key in commit.jira_keys:
                    if jira_key_string:
                        jira_key_string += ','
                    jira_key_string += term.cyan(key)
                    if self.diffmode == DiffMode.JIRADETAILS:
                        if '-' not in key:
                            raise SyntaxError(f'Invalid ticket form "{key}". Expected "<jira-key>-<ticket-id>".')

                        jirakey = key.split('-', maxsplit=1)[0]
                        try:
                            jira_service = issueman.service(jirakey)
                            issue = jira_service.get_issue(key)
                            links = issue.get('fields', {}).get('issuelinks', [])
                            for link in links:
                                link_type = link.get('type', {}).get('inward')
                                linked_ticket = link.get('inwardIssue', {}).get('key')
                                linked_msg = link.get('inwardIssue', {}).get('fields', {}).get('summary')
                                if link_type and linked_ticket:
                                    jira_link_text += f'\n    {link_type} {term.cyan(linked_ticket)}: {linked_msg}'
                        except LookupError:
                            # Silently ignore errors. This can happen when jirakey is not
                            # registered in the current profile
                            pass
                        except Exception:
                            raise

                if not jira_key_string:
                    jira_key_string = term.yellow('(no ticket)')

                commit_msg = commit.message.split('\n')[0]

                text = f'{jira_key_string}: {commit_msg}'
                if jira_link_text:
                    text += jira_link_text

                if self.diffmode == DiffMode.GITDETAILS:
                    text += ( f'\n    commit URL: {commit.commit_url}'
                            + f'\n    git hash:   {commit.git_hash}'
                            + f'\n    committer:  {commit.author_email} ({commit.author_name})' )
                yield text


    def _git_commits(
        self,
        cmp_res: CompareResult,
        scmman: SCMManager,
    ) -> Iterator[GitCommit]:
        if cmp_res.state != CompareState.CHANGED:
            return

        since = cmp_res.pkg_a.git_hash
        until = cmp_res.pkg_b.git_hash

        url = cmp_res.pkg_a.git_repo
        if not url:
            return

        service = scmman.service(url=url)

        yield from service.get_commits(since=since, until=until, limit=self.max_git_commits)

