#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json

from pathlib import Path
from typing import List, Iterator
from urllib.parse import urlparse


from rbbuild.core.channel import Channel
from rbbuild.core.temp_folder import TempFolder
from rbbuild.package.component import Component
from rbbuild.package.manifest import Manifest
from rbbuild.package.package import Package
from rbbuild.service.rest_helper import RESTHelper

from .repository import Repository


class URLService(Repository):
    def __init__(
        self,
        channel: Channel,
        manifest: Manifest,
        temp_folder: TempFolder,
        url: str,
        user: str,
        auth_method: str,
        cache,
        credentials,
        truststore: bool,
    ):
        Repository.__init__(
            self,
            channel=channel,
            cache=cache,
            manifest=manifest,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )
        self.temp_folder = temp_folder
        self.CHUNK_BLOCK_SIZE = 65536


    @property
    def tmpdir(self):
        return self.temp_folder.path


    def resource_url(self, pkg: Package) -> str:
        return pkg.url


    def get_versions(self, name: str) -> List[str]:
        return [name]


    # Download manifest and return Path (temp)
    def get_package(self, pkg: Package) -> Path:
        url = urlparse(pkg.url)
        filename = Path(url.path).name

        manifest_data = {
            'json_version': 5,
            'package': {
                'version_package': pkg.name,
                'version_string': pkg.version,
                'url': pkg.url,
                'components': [{
                    'name': filename,
                    'suffix': None,
                    'filename': filename,
                    'checksum': None,
                }],
            }
        }

        localfile = self.tmpdir / f'{pkg.name}-{pkg.version}-manifest.json'
        with open(localfile, 'w') as fd:
            json.dump(manifest_data, fd, indent=4)

        return localfile


    def get_component(
        self,
        pkg: Package,
        component: Component,
    ) -> Path:
        rest_helper = RESTHelper(self.tmpdir, progress_cb=self.progress_cb, session=self.session)
        localfile = rest_helper.download_file(
            url=pkg.url,
            headers=self.headers,
            auth=self.auth,
        )
        return localfile


    # Delete package version, return True if file deletion was executed
    def delete(
        self,
        name: str,
        version: str,
    ) -> bool:
        raise


    def upload_component(
        self,
        name: str,
        version: str,
        component: Component,
    ):
        raise


    def list_package_names(self, pattern: str) -> Iterator[str]:
        raise


    # Return all manifest filenames for an exact name+version
    # (e.g. ['boost-1.0-linux-native-manifest.json', 'boost-1.0-native-manifest.json'])
    def list_manifest_names(self, name: str, version: str) -> List[str]:
        raise

