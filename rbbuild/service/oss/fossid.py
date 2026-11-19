#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List
from enum import Enum

from rbbuild.core.runtime_settings import OperationMode
from rbbuild.librbb.term import term
from rbbuild.package.package import Package

from rbbuild.service.remote_service import RemoteService, AuthMethod


@dataclass
class FossIDProjectEntry:
    project_code: str
    description: str
    comment: str
    project_id: int

    def __str__(self):
        return ( f'\tproject code/name: {term.bright_white(self.project_code)} (id: {term.cyan(str(self.project_id))})\n'
               + f'\tproject description: {self.description}\n'
               + f'\tproject comment: {self.comment}\n' )


@dataclass
class FossIDScanEntry:
    project_entry: FossIDProjectEntry
    scan_code: str
    description: str
    comment: str
    git_repo: str
    git_hash: str
    scan_id: int
    jar_file_extraction: str='never'

    def __str__(self):
        return ( f'\tscan code/name: {term.bright_white(self.scan_code)} (id: {term.cyan(str(self.scan_id))})\n'
               + f'\tscan description: {self.description}\n'
               + f'\tGit resources: URL: {self.git_repo}, revision: {self.git_hash}\n'
               + f'\tscan comment: {self.comment}\n'
               + f'\tJAR file extraction mode: {self.jar_file_extraction}\n'
               )


class IgnoreRuleType(Enum):
    FILE = 'file'
    DIRECTORY = 'directory'
    FOLDER = 'directory'
    EXTENSION = 'extension'


class FossID(RemoteService):
    def __init__(
        self,
        name: str,
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        project_org_prefix: str,
        op_mode: OperationMode,
        truststore: bool,
    ):
        RemoteService.__init__(
            self,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.name = name
        self.project_org_prefix = project_org_prefix
        self.op_mode = op_mode
        self.headers['Content-type'] = 'application/json'


    @property
    def api_endpoint_url(self) -> str:
        endpoint = self.url
        if not endpoint.endswith('/'):
            endpoint += '/'
        return f'{endpoint}api.php'


    def project_code(self, pkg: Package) -> str:
        return f'{self.project_org_prefix}_{pkg.name}'


    def scan_code(self, pkg: Package) -> str:
        return f'{self.project_code(pkg)}-{pkg.version}'


    def scan_url(self, scan_id: int) -> str:
        return f'{self.url}index.html?action=scanview&sid={scan_id}'


    #
    # REST API calls
    #

    def get_project(self, pkg: Package) -> FossIDProjectEntry:
        payload = {
            'group': 'projects',
            'action': 'get_information',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': self.project_code(pkg),
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == '1':
            return FossIDProjectEntry( project_code=payload['data']['project_code'],
                                       description=data['data']['description'],
                                       comment=data['data']['comment'],
                                       project_id=int(data['data']['id']) )



    def create_project(self, pkg: Package, project_description: str) -> FossIDProjectEntry:
        payload = {
            'group': 'projects',
            'action': 'create',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': self.project_code(pkg),
                'project_name': self.project_code(pkg),
                'description': project_description,
                'comment': 'FossID project created with rbbuild',
            }
        }
        # TODO:
        #if self.settings.profile.jira:
        #    # Note: it is assumed that the first Jira project key (if it exists) is
        #    # the primary one.
        #    payload['data']['jira_project_key']: next(iter(self.settings.profile.jira))

        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != '1':
            raise RuntimeError(f'Could not create {term.bright_white(self.project_code(pkg))}: {data.get("error")}')

        return FossIDProjectEntry( project_code=payload['data']['project_code'],
                                   description=payload['data']['description'],
                                   comment=payload['data']['comment'],
                                   project_id=int(data['data']['project_id']) )


    def get_scan(self, pkg: Package, fossid_project: FossIDProjectEntry) -> FossIDScanEntry:
        payload = {
            'group': 'scans',
            'action': 'get_information',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': self.scan_code(pkg),
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == '1':
            if int(data['data']['project_id']) != fossid_project.project_id:
                raise RuntimeError(f'Scan {payload["data"]["scan_code"]} has an invalid project ID {data["data"]["project_id"]}')

            return FossIDScanEntry( project_entry=fossid_project,
                                    scan_code=payload['data']['scan_code'],
                                    description=data['data']['description'],
                                    comment=data['data']['comment'],
                                    scan_id=int(data['data']['id']),
                                    git_repo=data['data']['git_repo_url'],
                                    git_hash=data['data']['git_branch'] )


    def create_scan(self, pkg: Package, fossid_project: FossIDProjectEntry) -> FossIDScanEntry:
        payload = {
            'group': 'scans',
            'action': 'create',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': fossid_project.project_code,
                'scan_code': self.scan_code(pkg),
                'scan_name': self.scan_code(pkg),
                'description': str(pkg),
                'comment': 'FossID project created with rbbuild',
                'git_repo_url': pkg.git_repo,
                'git_branch': pkg.git_hash,
                'git_ref_type': 'commit',
                'jar_file_extraction': 'if_no_fullmatch',
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != '1':
            raise RuntimeError(f'Could not create {term.bright_white(self.scan_code(pkg))}: {data.get("error")}:\n{data.get("data", [{}])[0].get("message")}')

        return FossIDScanEntry( project_entry=fossid_project,
                                scan_code=payload['data']['scan_code'],
                                description=payload['data']['description'],
                                comment=payload['data']['comment'],
                                git_repo=payload['data']['git_repo_url'],
                                git_hash=payload['data']['git_branch'],
                                scan_id=int(data['data']['scan_id']) )


    def _do_download_content_from_git_new(self, fossid_scan: FossIDScanEntry):
        payload = {
            'group': 'scans',
            'action': 'download_content_from_git',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != '1':
            raise RuntimeError(f'Scan {payload["data"]["scan_code"]}: failed to initiate download from git')


    def download_content_from_git(self, fossid_scan: FossIDScanEntry) -> Iterator[str]:
        payload = {
            'group': 'scans',
            'action': 'check_status_download_content_from_git',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
            }
        }
        json_data = json.dumps(payload)
        while True:
            resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
            resp.raise_for_status()
            data = resp.json()
            if data.get('status') != '1':
                raise RuntimeError(f'Scan {payload["data"]["scan_code"]}: failed to retrieve download status from git')

            if data['data'] == 'NOT STARTED':
                self._do_download_content_from_git_new(fossid_scan)

            elif data['data'] in ['FINISHED', 'FAILED']:
                break

            yield data['data']
            time.sleep(1)



    # Issue a FossID scan run call
    def _scans_run(self, fossid_scan: FossIDScanEntry):
        payload = {
            'group': 'scans',
            'action': 'run',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
            }
        }

        # A full scan is performed if:
        # * Explicitly requested (via rbfoss -f)
        # * This is the first scan
        #
        # Otherwise, the scan identification is reused from the current project
        run_full_scan = False
        if self.op_mode.force is True:
            run_full_scan = True
        else:
            scans = self.get_all_scans(fossid_scan.project_entry)
            if not scans or len(scans) <= 1:
                run_full_scan = True

        if run_full_scan is False:
            payload['data']['reuse_identification'] = '1'
            payload['data']['identification_reuse_type'] = 'specific_project'
            payload['data']['specific_project'] = fossid_scan.project_entry.project_code

        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != '1':
            raise RuntimeError(f'Scan {payload["data"]["scan_code"]}: failed to retrieve download status from git')



    def run(self, fossid_scan: FossIDScanEntry) -> Iterator[str]:
        payload = {
            'group': 'scans',
            'action': 'check_status',
            'type': 'SCAN',
            'delay_response': 1,
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
            }
        }
        json_data = json.dumps(payload)
        while True:
            resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
            resp.raise_for_status()
            data = resp.json()
            if data.get('status') != '1':
                raise RuntimeError(f'Scan {payload["data"]["scan_code"]}: failed to retrieve download status from git')

            # Once started, data['data']['status'] is True (WTF ...)
            if data['data']['status'] == 'NEW':
                self._scans_run(fossid_scan)

            elif data['data']['status'] in ['FINISHED', 'FAILED']:
                break

            yield data['data']['status']


    def delete_scan(self, fossid_scan: FossIDScanEntry):
        payload = {
            'group': 'scans',
            'action': 'delete',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
                # 'delete_identifications': '1'  --> if --force?
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get('status', False))


    def get_all_scans(self, fossid_project: FossIDProjectEntry) -> List[FossIDScanEntry]:
        payload = {
            'group': 'projects',
            'action': 'get_all_scans',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': fossid_project.project_code,
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()

        if data.get('status') != '1':
            raise RuntimeError(f'Failed to retrieve all scans of project {payload["data"]["project_code"]}: {resp.text}')

        scans = []
        for entry in data['data']:
            scan = FossIDScanEntry( project_entry=None,
                                    scan_code=entry['code'],
                                    description=entry['description'],
                                    comment=entry['comment'],
                                    git_repo=entry['git_repo_url'],
                                    git_hash=entry['git_branch'],
                                    scan_id=int(entry['id']) )
            scans.append(scan)

        return scans


    def delete_project(self, fossid_project: FossIDProjectEntry) -> bool:
        scans = self.get_all_scans(fossid_project)

        if scans:
            raise RuntimeError(f'Cannot delete FossID project {term.bright_white(fossid_project.project_code)}: contains {term.cyan(str(len(scans)))} scans')

        payload = {
            'group': 'projects',
            'action': 'delete',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': fossid_project.project_code,
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get('status', False))


    def generate_report(
        self,
        report_path: Path,
        fossid_scan: FossIDScanEntry,
        report_type: str,
    ):
        payload = {
            'group': 'scans',
            'action': 'generate_report',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
                'report_type': report_type,
                'selection_type': 'include_all_licenses',
                # 'selection_view': ['pending_identification', 'marked_as_identified']
                # 'disclaimer': 'disclaimer'

            }
        }
        json_data = json.dumps(payload)
        if report_type == 'xlsx':
            headers = {'Content-type': 'application/vnd.ms-excel'}
        elif report_type == 'html':
            headers = {'Content-type': 'text/html'}
        else:
            raise NotImplementedError(f'FossID report_type {report_type} is not implemented')

        resp = self.session.post(url=self.api_endpoint_url, headers=headers, data=json_data)
        resp.raise_for_status()

        if report_type == 'xlsx':
            with open(report_path, 'wb') as fd:
                fd.write(resp.content)
        elif report_type == 'html':
            with open(report_path, 'w', encoding='utf-8') as fd:
                fd.write(resp.text)


    def assign_member(self, fossid_project: FossIDProjectEntry, user: str) -> bool:
        payload = {
            'group': 'projects',
            'action': 'assign_member',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'project_code': fossid_project.project_code,
                'assign_member': user,
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get('status', False))


    def cancel_run(self, fossid_scan: FossIDScanEntry) -> bool:
        payload = {
            'group': 'scans',
            'action': 'cancel_run',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get('status', False))


    def ignore_rules_add(self, fossid_scan: FossIDScanEntry, ignore_rule_type: IgnoreRuleType, item: str) -> bool:
        payload = {
            'group': 'scans',
            'action': 'ignore_rules_add',
            'data': {
                'username': self.auth[0],
                'key': self.auth[1],
                'scan_code': fossid_scan.scan_code,
                'type': ignore_rule_type.value,
                'value': item,
                'apply_to': 'scan',
            }
        }
        json_data = json.dumps(payload)
        resp = self.session.post(url=self.api_endpoint_url, headers=self.headers, data=json_data)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get('status', False))

