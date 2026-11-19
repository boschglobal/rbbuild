#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import argparse
import json
import os
import multiprocessing
import shutil
import sys

from dependency_injector.wiring import Provide, inject
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Callable, Optional

from rbbuild.buildsystem.cmake import CMake
from rbbuild.buildsystem.ctest import CTest
from rbbuild.buildsystem.npm import NPM
from rbbuild.buildsystem.pypa import PyPA
from rbbuild.buildsystem.pytest import PyTest
from rbbuild.buildsystem.rbbuild_class import RBBuild
from rbbuild.buildsystem.ruff import Ruff

from rbbuild.deps.parser import DepsParser
from rbbuild.core.cache import CacheMode
from rbbuild.core.channel import Channel
from rbbuild.core.paths import Paths
from rbbuild.core.runtime_settings import RuntimeSettings
from rbbuild.core.toolchain import Toolchain

from rbbuild import data_path
from rbbuild.container.application import Application
from rbbuild.container.configuration import RBBuildConfiguration
from rbbuild.docsystem.documentation_runner import DocumentationRunner

from rbbuild.generate.project_file_generator import ProjectFileGenerator
from rbbuild.librbb.term import term, LogLevel

from rbbuild.package.component import Component
from rbbuild.package.package import Package
from rbbuild.package.manifest import Manifest
from rbbuild.package.metadata import Metadata

from rbbuild.resolver.resolver import Resolver
from rbbuild.service.ci.manager import CIManager
from rbbuild.service.repository.manager import RepositoryManager
from rbbuild.service.repository.repository import VersionConflictError
from rbbuild.service.utility import bump_conflict_version
from rbbuild.sourcedir.staging_folder import StagingFolder


class RBBuildMain:
    def __init__(self):
        self._mypkg: Package = None

    # Create Package object
    @inject
    def make_mypkg(
        self,
        paths: Paths         = Provide[Application.core.paths],
        channel: Channel     = Provide[Application.core.channel],
        toolchain: Toolchain = Provide[Application.core.toolchain],
        metadata: Metadata   = Provide[Application.package.metadata],
        repoman: RepositoryManager = Provide[Application.service.repository.repoman],
        ciman: CIManager     = Provide[Application.service.ci.ciman],
        ci_key: str          = Provide[Application.config.settings.ci],
        supplier: dict       = Provide[Application.config.profile.supplier],
    ) -> Package:
        mypkg = Package(name=metadata.name, version=str(metadata.version))
        mypkg.branch = metadata.branch
        mypkg.channel = channel
        mypkg.toolchain = None if toolchain.is_any else toolchain
        mypkg.git_hash = metadata.git_hash
        mypkg.git_repo = metadata.git_repo
        mypkg.supplier = supplier or None
        mypkg.build_url = None
        if ci_key:
            try:
                mypkg.build_url = ciman.service(ci_key).job_url()
            except LookupError:
                pass
        mypkg.url = repoman.service(channel).resource_url(mypkg)

        return mypkg


    @property
    def mypkg(self) -> Package:
        if not self._mypkg:
            self._mypkg = self.make_mypkg()
        return self._mypkg


    @mypkg.setter
    def mypkg(self, pkg: Package):
        self._mypkg = pkg


    @inject
    def list_toolchains(
        self,
        selected_toolchain: Toolchain = Provide[Application.core.toolchain],
        selected_platform: str = Provide[Application.config.settings.platform],
        paths: Paths = Provide[Application.core.paths],
        toolchains: dict = Provide[Application.config.profile.toolchains],
    ):
        term.info(f'Staging directory: {paths.staging} [{selected_toolchain.name}]')
        term.info(f'Available toolchains ({selected_platform})')
        term.print_line()
        for i, (tcid, toolchain) in enumerate(toolchains.items()):
            if not tcid.startswith(f'{selected_platform}-') and not tcid.startswith('none-'):
                continue
            if str(selected_toolchain) == tcid or selected_toolchain.name == tcid:
                defstr = term.green('*')
            else:
                defstr = ' '
            idxstr = term.bright_white(f'{i+1:>2}')
            term.info(f'[{idxstr}] {defstr}{tcid}')
        term.print_line()


    @inject
    def generate_path(
        self,
        generate_path: Path,
        files: list = None,
        generator: ProjectFileGenerator = Provide[Application.generate.project_file_generator],
    ):
        dest_path = Path(generate_path)
        pkgname = self.mypkg.name
        generator.create_files(
            dest_path=dest_path,
            pkgname=pkgname,
            files=files,
        )


    def load_cli_rbbuild(self, config: RBBuildConfiguration, args):
        if args.action:
            action = args.action
        else:
            action = list(config.rbbuild.actions() or config.tool.rbbuild.actions())

        # --upload [<channel>:]<pkg>-<version> <file1> [<file2> ...]
        if args.upload:
            # Any deps string is accepted, however '@' or '-' must be present to ensure a version is defined
            if not args.targets or ('-' not in args.upload and '@' not in args.upload):
                cmd = 'rbbuild --upload [<channel>:]<pkg>-<version> <file1> [<file2> ...]'
                raise SyntaxError( f'No files for upload defined. Allowed syntax:\n\t{term.cyan(cmd)}')

        if args.targets:
            # Building specific targets always implies a call to setup.
            # The reason is that specific targets could change, e.g., debug
            # vs non-debug builds
            action.append('setup')

        if args.execute:
            action.append('execute')

        # Deduplicate action commands
        action = list(set(action))
        config.tool.rbbuild.actions.from_value(action)

        # Disable synchronizing with remote if -F was not specified
        if 'fetch' not in action and 'publish' not in action:
            if config.cache_mode() == CacheMode.normal:
                config.cache_mode.from_value(CacheMode.cache_only)

        if args.cmake_define:
            config.tool.rbbuild.cmake.cmake_defines.from_value(args.cmake_define)


    # The list of a project's [tool.rbbuild] overrides the default of rbbuild.toml
    @inject
    def tool_list(
        self,
        key: str,
        project_config: dict = Provide[Application.config.rbbuild],
        default_config: dict = Provide[Application.config.tool.rbbuild],
    ) -> Optional[List[str]]:
        value = (project_config or {}).get(key)
        if value is None:
            value = (default_config or {}).get(key)
        return value


    @inject
    def build_tools(
        self,
        build_tools_config: List[str] = None,
        cmake: CMake = Provide[Application.buildsystem.cmake],
        pypa: PyPA = Provide[Application.buildsystem.pypa],
        npm: NPM = Provide[Application.buildsystem.npm],
        rbbuild: RBBuild = Provide[Application.buildsystem.rbbuild],
    ) -> list:
        if build_tools_config is None:
            build_tools_config = self.tool_list('build_tools') or []

        tools = []

        for tool in build_tools_config:
            if tool == 'cmake' and cmake.available:
                tools.append(cmake)
            elif tool == 'pypa' and pypa.available:
                tools.append(pypa)
            elif tool == 'npm' and npm.available:
                tools.append(npm)
            elif tool == 'rbbuild':
                tools.append(rbbuild)

        return tools


    # Without test-tools, the tests of the build tools run (ctest for CMake,
    # pytest for pypa). Otherwise, exactly the configured tools run.
    @inject
    def test_tools(
        self,
        test_tools_config: List[str] = None,
        ctest: CTest = Provide[Application.buildsystem.ctest],
        pytest: PyTest = Provide[Application.buildsystem.pytest],
    ) -> list:
        if test_tools_config is None:
            test_tools_config = self.tool_list('test_tools')
        if test_tools_config is None:
            test_tools_config = []
            for pkgman in self.build_tools():
                if isinstance(pkgman, CMake):
                    test_tools_config.append('ctest')
                elif isinstance(pkgman, PyPA):
                    test_tools_config.append('pytest')

        tools = []

        for tool in test_tools_config:
            if tool == 'ctest' and ctest.available:
                tools.append(ctest)
            elif tool == 'pytest':
                tools.append(pytest)

        return tools


    @inject
    def sca_tools(
        self,
        sca_tools_config: List[str] = None,
        ruff: Ruff = Provide[Application.buildsystem.ruff],
    ) -> list:
        if sca_tools_config is None:
            sca_tools_config = self.tool_list('sca_tools') or []

        tools = []

        for tool in sca_tools_config:
            if tool == 'ruff' and ruff.available:
                tools.append(ruff)

        return tools


    # args.tcid and args.force controls the behavior of clean:
    # - rbbuild -c            remove obj (all toolchains)
    # - rbbuild -cf:          remove obj and staging (all toolchains)
    # - rbbuild -c -t <tcid>  remove obj/<tcid>
    # - rbbuild -cf -t <tcid> remove obj/<tcid> and staging/<tcid>
    @inject
    def clean(
        self,
        remove_staging: bool,
        all_toolchains: bool = False,
        paths: Paths = Provide[Application.core.paths],
        staging_folder: StagingFolder = Provide[Application.sourcedir.staging_folder],
    ):
        term.debug('action', 'clean')
        # Package manager specific cleanup, if any
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'clean'):
                term.debug(f'Cleaning up ... ({type(pkgman).__name__})')
                pkgman.clean(remove_staging)

        # Finalize cleanup
        if paths.build.exists():
            term.info(f'Removing {paths.build} ...')
            shutil.rmtree(paths.build, ignore_errors=True)

        # By default, documentation root is also obj
        if paths.documentation.exists():
            term.info(f'Removing {paths.documentation} ...')
            shutil.rmtree(paths.documentation, ignore_errors=True)

        if all_toolchains:
            if paths.build_root.exists():
                term.info(f'Removing {paths.build_root} ...')
                shutil.rmtree(paths.build_root, ignore_errors=True)
        else:
            # Now that obj/<tcid> is gone, attempt to remove obj
            try:
                paths.build.parent.rmdir()
            except OSError:
                pass

        if remove_staging:
            if not all_toolchains:
                staging_folder.remove()
            elif paths.staging_root.exists():
                term.info(f'Removing {paths.staging_root} ...')
                shutil.rmtree(paths.staging_root, ignore_errors=True)


    def fetch(self, fi_hint: bool):
        term.debug('action', 'fetch')
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'fetch'):
                term.debug(f'Downloading dependencies ... ({type(pkgman).__name__})')
                pkgman.fetch(self.mypkg, fi_hint=fi_hint)

        # TODO: code disabled for now
        # If -FI was called, but nothing was found, the
        # install_deps part is auto-removed to avoid errors in the build
        #if not self.mypkg.dependencies and 'install_deps' in action:
        #    actions.remove('install_deps')


    @inject
    def install_deps(
        self,
        fi_hint: bool,
        paths: Paths = Provide[Application.core.paths],
        staging_folder: StagingFolder = Provide[Application.sourcedir.staging_folder],
    ):

        term.debug('action', 'install_deps')
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'install_deps'):
                term.debug(f'Installing dependencies ... ({type(pkgman).__name__})')
                pkgman.install_deps(
                    mypkg=self.mypkg,
                    staging_folder=staging_folder,
                    install_prefix=paths.install_prefix,
                    fi_hint=fi_hint,
                )


    @inject
    def setup(
        self,
        paths: Paths = Provide[Application.core.paths],
    ):
        term.debug('action', 'setup')
        # ensure that obj/<tcid>/generated is created
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'setup'):
                term.debug(f'Setting up build ... ({type(pkgman).__name__})')
                pkgman.setup(install_prefix=paths.install_prefix)


    def build(self, build_targets: List[str], njobs: str):
        term.debug('action', 'build')
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'build'):
                term.debug(f'Building ... ({type(pkgman).__name__})')
                # rbbuild <target>...
                if build_targets:
                    # Handle optional make targets
                    for target in build_targets:
                        term.info(f'Build target {term.bright_white(target)} ({type(pkgman).__name__})')
                        pkgman.build(target=target, njobs=njobs)
                else:
                    pkgman.build(target=None, njobs=njobs)


    def static_code_analysis(self):
        term.debug('action', 'static_code_analysis')
        tools = self.sca_tools()
        if not tools:
            term.warning('sca', 'No static code analysis tool available')
            return
        for tool in tools:
            term.debug(f'Running static code analysis (SCA) ... ({type(tool).__name__})')
            tool.static_code_analysis()

        # Sonar is currently not functional. The code is kept for reference.
        # TODO: code from backend/cmake.py:
        #package_source_paths = self._package_source_paths()
        #sonar_build_wrapper = SonarBuildWrapper(self.settings)
        #if not package_source_paths:
        #    raise RuntimeWarning( 'Sonar scan enabled but RBPACKAGE_SOURCE_DIRS '
        #                          'is undefined in CMakeLists.txt' )
        #elif not sonar_build_wrapper.meta_files_exist():
        #    raise RuntimeError( 'Sonar build wrapper must be enabled and '
        #                        'rbbuild --build must be executed first' )
        #
        #else:
        #    term.info( 'Running sonar-scanner: %s'
        #             % ('\n[%s] ' % term.green('*')).join(['', *package_source_paths]) )
        #    sonar = SonarScanner(self.settings, metadata)
        #    sonar.run(package_source_paths)


    def install(self):
        term.debug('action', 'install')
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'install'):
                term.debug(f'Installing packages into local staging folder ... ({type(pkgman).__name__})')
                pkgman.install()


    def run_tests(self):
        term.debug('action', 'run_tests')
        for tool in self.test_tools():
            term.debug(f'Running tests ... ({type(tool).__name__})')
            tool.run_tests()


    @inject
    def documentation(
        self,
        documentation_runner: DocumentationRunner = Provide[Application.docsystem.documentation_runner],
    ):
        term.debug('action', 'documentation')
        documentation_runner.build_documentation(self.mypkg)


    @inject
    def run_executable(
        self,
        target: str,
        extra_args: List[str],
        paths: Paths = Provide[Application.core.paths],
    ):
        term.debug('action', 'execute')
        if not extra_args:
            extra_args = []
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'execute'):
                term.debug(f'Running executable {target} {" ".join(extra_args)} ... ({type(pkgman).__name__})')
                pkgman.execute(target, extra_args, install_prefix=paths.install_prefix)


    @inject
    def package(
        self,
        paths: Paths = Provide[Application.core.paths],
    ):
        term.debug('action', 'package')
        if not paths.build.exists():
            term.warning('No object folder', 'Did you call rbbuild -sb?')
            return

        # Build tools run in config order so each can consume the prior tool's
        # artifacts (e.g. rbbuild archives bundled into a pypa wheel).
        # write_manifest() is called once after all tools so the manifest and
        # SBOM capture every component, including pypa sdist/wheel.
        rbbuild_tool = None
        for pkgman in self.build_tools():
            if hasattr(pkgman, 'package'):
                term.debug(f'Packaging ... ({type(pkgman).__name__})')
                pkgman.package(self.mypkg)
            if isinstance(pkgman, RBBuild):
                rbbuild_tool = pkgman

        if rbbuild_tool:
            rbbuild_tool.write_manifest(self.mypkg)


    def _load_pkg_for_publish(
        self,
        chname: str,
        paths: Paths,
        manifest: Manifest,
        channel_factory: Callable[..., Channel],
    ):
        # The latest package content is loaded from manifest to ensure all dependencies are correct.
        manifest_path = paths.build / 'manifest.json'
        if not manifest_path.exists():
            raise FileNotFoundError('Package not found. Did you call rbbuild -p?')

        with open(manifest_path, 'r') as jfd:
            data = json.load(jfd)
            self.mypkg = manifest.manifest_parser.parse(data)
            if not self.mypkg:
                raise RuntimeError(f'Failed to parse {manifest_path}')

        self.mypkg.manifest = Component(
            name='manifest',
            suffix='json',
            localpath = manifest_path,
            filename = manifest.make_filename(
                self.mypkg.name,
                self.mypkg.version,
                self.mypkg.toolchain,
            ),
        )

        for component in self.mypkg.components:
            component.localpath = paths.build / component.filename

        self.mypkg.channel = channel_factory(name=chname)

        if self.mypkg.channel.permissions not in ['delete', 'overwrite', 'upload']:
            raise PermissionError(f'No permission to upload from {term.bright_white(chname)}: maximum permission level is set to {term.red(self.mypkg.channel.permissions)}')


    @inject
    def publish(
        self,
        chname: str,
        paths: Paths = Provide[Application.core.paths],
        manifest: Manifest = Provide[Application.package.manifest],
        channel_factory: Callable[..., Channel] = Provide[Application.core.channel_factory],
    ):
        term.debug('action', f'publish [{chname}]')
        self._load_pkg_for_publish(chname, paths, manifest, channel_factory)

        while True:
            try:
                for pkgman in self.build_tools():
                    if hasattr(pkgman, 'publish'):
                        term.debug(f'Publishing ... ({type(pkgman).__name__})')
                        pkgman.publish(self.mypkg)
                return
            except VersionConflictError as conflict:
                new_version = bump_conflict_version(self.mypkg.version)
                term.warning(
                    'Version conflict',
                    f'{conflict} Retrying as {term.bright_white(new_version)} ...',
                )
                self.mypkg.version = new_version
                self.mypkg.components = []
                self.mypkg.tools = []
                self.package()
                self._load_pkg_for_publish(chname, paths, manifest, channel_factory)


    @inject
    def upload(
        self,
        deps_item: str,
        files: List[str],
        repoman: RepositoryManager = Provide[Application.service.repository.repoman],
        deps_parser: DepsParser = Provide[Application.deps.parser],
        manifest: Manifest = Provide[Application.package.manifest],
        toolchain: Toolchain = Provide[Application.core.toolchain],
    ):
        term.debug('actions', f'upload [{deps_item}] [{files}]')
        pkg = deps_parser.parse_item(item=deps_item)
        if not pkg.toolchain:
            pkg.toolchain = toolchain
        for target in files:
            localpath = Path(target)
            if not localpath.exists():
                raise FileNotFoundError(f'File does not exist: {target}')

            name = localpath.name
            if '.' in target:
                name, suffix = name.rsplit('.', maxsplit=1)
            else:
                suffix = None

            component = Component(
                name=name,
                suffix=suffix,
                filename=localpath.name,
                localpath=localpath,
            )
            pkg.components.append(component)

        manifest_data = manifest.from_package(pkg)
        with NamedTemporaryFile(mode='w', delete=True, delete_on_close=False) as manifest_tempfile:
            json.dump(manifest_data, manifest_tempfile.file, indent=4)
            manifest_tempfile.close()
            filename = manifest.make_filename(
                pkg.name,
                pkg.version,
                pkg.toolchain,
            )
            pkg.manifest = Component(
                name = filename,
                suffix = None,
                localpath = Path(manifest_tempfile.name),
                filename = filename,
            )

            channel_name = pkg.channel.name if pkg.channel else str(repoman.selected_channel)
            term.info(f'Uploading package {term.bright_white(str(pkg))} to channel {term.bright_white(channel_name)}')

            for component in repoman.upload(pkg):
                term.redraw_last_line(f' ... {term.green("success")}')


    @inject
    def delete(
        self,
        target: str,
        repoman: RepositoryManager = Provide[Application.service.repository.repoman],
    ):
        for pkg in repoman.search_versions(deps_item=target):
            repoman.delete(pkg)
            # Only delete the first item
            break


    @inject
    def licenses(
        self,
        paths: Paths = Provide[Application.core.paths],
        manifest: Manifest = Provide[Application.package.manifest],
        resolver: Resolver = Provide[Application.resolver.resolver],
    ):
        def _show_license(pkg):
            if pkg.licenses:
                term.info('License: ', end='')
                if len(pkg.licenses) == 1:
                      term.info(str(pkg.licenses[0]))
                else:
                    term.info('\n    ' + '\n    '.join([str(lic) for lic in pkg.licenses]))

        def _show_copyright(pkg):
            if pkg.copyright:
                term.info(f'Copyright: {pkg.copyright}')

        manifest_path = paths.build / 'manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('Package information is unavailable. Did you run rbbuild -sbp?')

        with open(manifest_path, 'r') as jfd:
            data = json.load(jfd)
            self.mypkg = manifest.manifest_parser.parse(data)
            if not self.mypkg:
                raise RuntimeError(f'Failed to parse {manifest_path}')

        term.info(f'{term.bright_white(str(self.mypkg))}')
        _show_license(self.mypkg)
        _show_copyright(self.mypkg)

        for child, _ in resolver.walk_deps_with_count(self.mypkg, skip_build_only=True):
            if child == self.mypkg:
                continue
            term.info(term.bright_white(str(child)))
            _show_license(child)
            _show_copyright(child)


    @inject
    def main(
        self,
        args,
        settings: RuntimeSettings = Provide[Application.core.settings],
        rbbuild_config: dict = Provide[Application.config.tool.rbbuild],
        toolchain: Toolchain = Provide[Application.core.toolchain],
    ):
        # --list
        if args.list:
            self.list_toolchains()
            return

        # --generate
        if args.generate_path:
            self.generate_path(args.generate_path, files=args.generate_files)
            return

        # --version
        if args.version:
            from rbbuild.version import __version__
            term.info(__version__)
            return

        # rbbuild --upload
        if args.upload:
            self.upload(deps_item=args.upload, files=args.targets)
            return

        # rbbuild --delete
        if args.delete:
            msg = f'delete {term.bright_white(args.delete)}'
            if args.channel:
                msg += f' from channel {term.bright_white(args.channel)}'
            term.debug('action', msg)
            self.delete(target=args.delete)
            return

        # rbbuild --licenses
        if args.licenses:
            self.licenses()
            return

        actions = rbbuild_config['actions']

        # -v
        if args.verbose:
            term.info('Build actions:', actions)
            if args.targets:
                term.info('Target:', args.targets)
            term.info('PATH:', os.environ['PATH'])

        term.info(f'Profile: {term.bright_white(settings.profile_name)}, toolchain: {term.bright_white(str(toolchain))}')
        term.debug('actions', f'[{", ".join([term.magenta(action) for action in actions])}]')

        fi_hint = 'fetch' in actions and 'install_deps' in actions

        # rbbuild -c
        if 'clean' in actions:
            self.clean(remove_staging=args.force, all_toolchains=not args.tcid)
            actions.remove('clean')

        # rbbuild -F
        if 'fetch' in actions:
            self.fetch(fi_hint=fi_hint)
            actions.remove('fetch')

        # rbbuild -I
        if 'install_deps' in actions:
            self.install_deps(fi_hint=fi_hint)
            actions.remove('install_deps')

        # rbbuild -s
        if 'setup' in actions:
            self.setup()
            actions.remove('setup')

        # rbbuild -b
        if 'build' in actions:
            self.build(build_targets=args.targets, njobs=args.jobs)
            actions.remove('build')

        # rbbuild --static-code-analysis
        if 'static_code_analysis' in actions:
            self.static_code_analysis()
            actions.remove('static_code_analysis')

        # rbbuild -i
        if 'install' in actions:
            self.install()
            actions.remove('install')

        # rbbuild -T
        if 'run_tests' in actions:
            self.run_tests()
            actions.remove('run_tests')

        # rbbuild --publish
        if 'publish' in actions:
            self.publish(args.channel)
            return

        # rbbuild -x
        if 'execute' in actions:
            self.run_executable(args.execute, args.extra_args)
            actions.remove('execute')

        # rbbuild -D / --documentation
        if 'documentation' in actions:
            self.documentation()
            actions.remove('documentation')

        # rbbuild -p
        if 'package' in actions:
            self.package()
            actions.remove('package')


def parse_command_line():
    parser = argparse.ArgumentParser(prog='rbbuild', description='rbbuild -- Robert Bosch tool for CMake-based projects')

    # Build actions
    parser.add_argument( '-s', '--setup',          action='append_const', dest='action', const='setup',         help='Setup' )
    parser.add_argument( '-S', '--setup-install-path', action='store',    dest='install_prefix',                help='Like --setup but with a custom install path (for NFS).' )
    parser.add_argument( '-b', '--build',          action='append_const', dest='action', const='build',         help='Build' )
    parser.add_argument( '-i', '--install',        action='append_const', dest='action', const='install',       help='Install compiled artifacts' )
    parser.add_argument( '-p', '--package',        action='append_const', dest='action', const='package',       help='Create artifact packages' )
    parser.add_argument( '-c', '--clean',          action='append_const', dest='action', const='clean',         help='Clean build directories' )
    parser.add_argument( '-F', '--fetch',          action='append_const', dest='action', const='fetch',         help='Fetch dependency packaged' )
    parser.add_argument( '-I', '--install-deps',   action='append_const', dest='action', const='install_deps',  help='Install dependencies' )
    parser.add_argument( '-T', '--run-tests',      action='append_const', dest='action', const='run_tests',     help='Execute tests' )
    parser.add_argument( '-D', '--documentation',  action='append_const', dest='action', const='documentation', help='Generate documentation' )
    parser.add_argument(       '--publish',        action='append_const', dest='action', const='publish',       help='Publish rbbuild package to a channel' )
    parser.add_argument(       '--upload',         action='store',        dest='upload', metavar='PACKAGE',     help='Upload package: --upload [<channel>:]<pkg>-<version> <file1> [<file2> ...]' )
    parser.add_argument(       '--delete',         action='store',        dest='delete', metavar='PACKAGE',     help='Delete packages' )
    parser.add_argument(       '--sca',            action='append_const', dest='action', const='static_code_analysis', help='Run static code analysis (SCA)' )
    parser.add_argument(       '--licenses',       action='store_const',  const=True,                                      help='List license information' )

    # Other actions
    parser.add_argument( '-l', '--list',           action='store_const',  const=True, default=False, help='List available toolchains and exit' )
    parser.add_argument( '-g', '--generate',       action='store',        dest='generate_path',      help='Generate missing project files and exit' )
    parser.add_argument(       '--generate-files',  action='store',        dest='generate_files',     nargs='+', metavar='FILE',
                               help='Files to generate with -g (default: rbbuild.toml Jenkinsfile + auto-detected). '
                                    'Choices: rbbuild.toml Jenkinsfile CMakeLists.txt pyproject.toml .gitignore tasks.json' )
    parser.add_argument( '-x', '--execute',        action='store',        dest='execute',            help='Execute a program obj/<tcid/' )

    # Options
    parser.add_argument( '-d', '--debug',          action='store_const',  const=True, default=False, help='Enable debug build' )
    parser.add_argument( '-j', '--jobs',           action='store',                                   help='Build with N parallel jobs (default: number of available CPUs)', type=int, default = multiprocessing.cpu_count() )
    parser.add_argument( '-t', '--toolchain',      action='store',        dest='tcid',               help='Select toolchain by name or ID' )
    parser.add_argument( '-f', '--force',          action='store_const',  const=True, default=False, help='Force action (use with -F)' )
    parser.add_argument( '-P', '--profile',        action='store',                                   help='Select profile' )


    parser.add_argument( '-v', '--verbose',        action='store_const',  const=True, default=False, help='Verbose output' )
    parser.add_argument( '-n', '--dry-run',        action='store_const',  const=True, default=False, help='Do not actually publish, only dry run (--publish)' )
    parser.add_argument(       '--define',         action='append',       dest='cmake_define',       help='Add CMake definition' )
    parser.add_argument( '-L', '--deps-line',      action='store',        dest='deps_line',          help='Accept deps entries line (-L <deps>[,<deps>]' )

    parser.add_argument( '-C', '--channel',        action='store',        dest='channel',            help='Select a channel' )
    parser.add_argument(       '--components',     action='store',        dest='components',         help='Select a component (--component=<comp>[,<comp>...])' )
    parser.add_argument(       '--platform',       action='store',        dest='platform', default=sys.platform, help='Specify target platform' )
    parser.add_argument(       '--manifest-only',  action='store_const',  const=True, default=False, help='Only generate manifest (use with -F and/or -I)' )
    parser.add_argument(       '--depsfile',       action='store',        dest='depsfile',           help='Select dependencies file (--depsfile=<file>)' )
    parser.add_argument(       '--ignore-errors',  action='store_const',  const=True, default=False, help='Ignore dependency errors' )
    parser.add_argument(       '--offline',        action='store_const',  const=True, default=False, help='Do not connect to a server, work with download cache only' )
    parser.add_argument(       '--source-path',    action='store',        dest='source_path',         help='Path to source code (default: current working dir)' )

    parser.add_argument(       '--version',        action='store_const',  const=True, default=False, help='Display version and exit' )
    parser.add_argument(       '--log-level',      action='store',        dest='log_level',          help='Highest log level: %s. Default: INFO' % ', '.join(LogLevel.__members__.keys()))

    # Optional make targets
    parser.add_argument('targets',                 nargs='*',                                        help='Custom targets. Invoke "rbbuild help" to see available build targets')

    # TODO: If -- is in the command line, we need to strip them away before arparse.
    # Unfortunately, nargs=argparse.REMAINDER does not work as expected.
    if '--' in sys.argv:
        argv = sys.argv[1:]
        i = argv.index('--')
        args = parser.parse_args(argv[:i])
        args.extra_args = argv[i + 1:]
    else:
        parser.add_argument( '--', action='store',   dest='extra_args', nargs=argparse.REMAINDER,    help='Program arguments passed to application (-x/--execute)' )
        args = parser.parse_args()

    if args.action is None:
        args.action = []

    return args


def run():
    args = parse_command_line()

    # --log-level
    term.log_level = args.log_level

    rbbuild_root_path = Path(
        os.environ.get('RBB_ROOT') or
        Path(__file__).resolve().parent
    ).absolute()
    rbbuild_config_path = Path(
        os.environ.get('RBB_CONFIG_PATH') or
        data_path() / 'config'
    ).absolute()

    try:
        config = RBBuildConfiguration()
        config.load_configuration(rbbuild_root_path, rbbuild_config_path)

        config.load_cli_source_path(**vars(args))
        source_path = Path(config.paths.source())
        config.load_project_configuration(source_path)
        config.load_jenkinsfile(source_path)
        config.load_cli_profile(**vars(args))

        config.load_profile(
            profile_name=config.settings.profile(),
            rbbuild_config_path=rbbuild_config_path,
            user_config_path=Path(config.paths.user_config()),
        )

        # Main class initialization
        rbbuild = RBBuildMain()

        # Load CLI overrides
        config.load_cli(**vars(args))
        rbbuild.load_cli_rbbuild(config, args)

        application = Application(config=config)
        application.wire(modules=[__name__])

        rbbuild.main(args)
    except Exception as e:
        import traceback
        term.error('failed', e)
        term.debug('Exception stack', traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    run()

