# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import os
import re
import time
import sys

from git import Repo, InvalidGitRepositoryError
from packaging.version import Version
from pathlib import Path
from urllib.parse import urlparse

from rbbuild import data_path
from rbbuild.core.paths import Paths
from rbbuild.service.issuetracker.issuetracker_manager import Issue


class Metadata:
    def __init__(
        self,
        project_config: dict,
        paths: Paths,
        source_path: Path=None,
        toolchain = None,
        development: bool = False,
    ):
        self.config = project_config if project_config else {}
        self.paths = paths
        # when calling rbbuild --version, access to Paths object is not available
        if source_path:
            self.source_path = source_path
        else:
            self.source_path = paths.source

        self.toolchain = toolchain
        self.development_version = 1 if development else 0


    @property
    def name(self) -> str:
        name = None
        if 'name' in self.config:
            name = self.config['name']

        elif self.source_path.exists():
            try:
                repo = Repo(self.source_path)
                if 'origin' in repo.remotes:
                    remote = repo.remote('origin')
                    # Extract package name from URL, e.g., rbbuild:
                    #     ssh://git@git.service:7999/rbbuild/rbbuild.git
                    git_repo = urlparse(next(remote.urls))
                    name = git_repo.path.rsplit('/', maxsplit=1)[1].rsplit('.', maxsplit=1)[0]
            except InvalidGitRepositoryError:
                pass
            except Exception:
                raise
        else:
            return None

        # Fall back to local source path name
        if not name:
            name = self.source_path.name

        # Accept package name characters from [a-zA-Z0-9].
        # Everything else is replaced with _
        return re.sub(r'\W', '_', name)


    @property
    def major(self) -> int:
        if 'version_major' in self.config:
            return int(self.config['version_major'])
        version = self.config.get('version', '0.0')
        if '.' in version:
            return int(version.split('.', maxsplit=1)[0])

        return int(version)


    @property
    def minor(self) -> int:
        if 'version_minor' in self.config:
            return int(self.config['version_minor'])
        version = self.config.get('version', '0.0')
        if '.' in version:
            return int(version.split('.')[1])

        # Single digit version was specified (=major version).
        # However, rbbuild usually consists of 4 digits.
        return 0


    @property
    def revision(self) -> int:
        if 'version_revision' in self.config:
            return int(self.config['version_revision'])
        # version="x.x.R" was specified in config
        if 'version' in self.config and self.config['version'].count('.') > 2:
            return int(self.config['version'].split('.')[2])
        # Base date computed with the following command:
        #   echo "$(date --date='2018-04-16' +%s) / ((60*60*24))" | bc
        date_2018_04_16  = 17636
        return int(int(time.time()) / (60*60*24)) - date_2018_04_16


    @property
    def build(self) -> int:
        # It is likely that this variable is passed from CI,
        # e.g., as BUILD_NUMBER env variable from Jenkins
        if 'version_build' in self.config:
            return int(self.config['version_build'])

        # version="x.x.x.B" was specified in config
        if 'version' in self.config and self.config['version'].count('.') > 3:
            return int(self.config['version'].split('.')[3])

        return 0


    @property
    def branch(self) -> str:
        if 'branch' in self.config:
            return self.config['branch']

        branch = 'local'

        if not self.source_path.exists():
            return branch

        try:
            repo = Repo(self.source_path)
            if 'origin' in repo.remotes:
                # Extract package name from URL, e.g., rbbuild:
                #     ssh://git@git.service:7999/rbbuild/rbbuild.git
                if repo.head.is_detached is False:
                    branch = repo.head.ref.name
        except InvalidGitRepositoryError:
            pass
        except Exception:
            raise

        return branch


    @property
    def authors(self) -> list:
        return self.config.get('authors', [])


    @property
    def maintainers(self) -> list:
        return self.config.get('maintainers', [])


    @property
    def license(self) -> dict:
        return self.config.get('license')


    @property
    def version(self) -> Version:
        version_string = f'{self.major}.{self.minor}.{self.revision}.{self.build}'
        if self.development_version:
            local = re.sub(r'[\W_]', '.', Issue.branch_abbreviated(self.branch))  # replace all special characters with .
            local = re.sub(r'^\.*', '', local)          # must not start with '.'
            local = re.sub(r'\.*$', '', local)          # must not end with '.'
            local = re.sub(r'\.+', '.', local)          # must not contain multiple '.' in sequence
            version_string += f'.dev{self.development_version}+{local}'
        return Version(version_string)


    @property
    def git_hash(self) -> str:
        git_hash = None

        if not self.source_path.exists():
            return git_hash

        try:
            repo = Repo(self.source_path)
            if 'origin' in repo.remotes:
                git_hash = str(repo.head.commit)
        except InvalidGitRepositoryError:
            pass
        except Exception:
            raise

        return git_hash


    @property
    def git_repo(self) -> str:
        git_repo = None

        if not self.source_path.exists():
            return git_repo

        try:
            repo = Repo(self.source_path)
            if 'origin' in repo.remotes:
                remote = repo.remote('origin')
                git_repo = next(remote.urls)
        except InvalidGitRepositoryError:
            pass
        except Exception:
            raise

        return git_repo


    # This method copied os.environ and places rbbuild-specific
    # environment variables. It is supposed to be used by build backends
    @property
    def environ(self) -> dict:
        environ = os.environ.copy()

        # Ensure the venv's bin directory is on PATH so that tools installed
        # there are reachable by child processes even when the venv is not activated.
        # It is assumed that Python is run from venv, not outside (=sys.executable).
        venv_bin = str(Path(sys.executable).parent)
        current_path = environ.get('PATH', '')
        if venv_bin not in current_path.split(os.pathsep):
            environ['PATH'] = venv_bin + os.pathsep + current_path

        # CMake's FindPython prefers the venv python only if VIRTUAL_ENV is set;
        # PATH alone is ignored in favor of registered/system interpreters.
        # A python toolchain comes first in PATH instead.
        python = self.toolchain.python_path if self.toolchain else None
        if python:
            environ['PATH'] = str(python.parent) + os.pathsep + environ['PATH']
        elif sys.prefix != sys.base_prefix:
            environ['VIRTUAL_ENV'] = sys.prefix

        environ.update({
            'RBB_ROOT'             : str(self.paths.rbbuild_root),
            'RBB_CONFIG_PATH'      : str(data_path()),
            'RBB_DIST_PATH'        : str(self.paths.dist),
            'RBB_SOURCE_PATH'      : str(self.paths.source),
            'RBB_BUILD_PATH'       : str(self.paths.build),
            'RBB_STAGING_PATH'     : str(self.paths.staging),
            'RBB_TOOLCHAIN_ID'     : str(self.toolchain),
            'RBB_PACKAGE_NAME'     : self.name,
            'RBB_PACKAGE_MAJOR'    : str(self.major),
            'RBB_PACKAGE_MINOR'    : str(self.minor),
            'RBB_PACKAGE_REVISION' : str(self.revision),
            'RBB_PACKAGE_BRANCH'   : str(self.branch),
            'RBB_PACKAGE_BUILD'    : str(self.build),
            'RBB_PACKAGE_VERSION'  : str(self.version),
        })
        if self.git_repo:
            environ['RBB_GIT_REPO'] = self.git_repo
        if self.git_hash:
            environ['RBB_GIT_HASH'] = self.git_hash

        if self.toolchain:
            environ = self.toolchain.apply_python_environment(environ)

        return environ



