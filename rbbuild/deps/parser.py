# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import ast
import fnmatch
import re

from copy import copy
from dataclasses import dataclass
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from typing import Dict, Tuple, List, Iterator, Union, Callable

from rbbuild.core.channel import Channel
from rbbuild.core.toolchain import Toolchain
from rbbuild.deps.purl_parser import PURLParser
from rbbuild.package.component import resolve_traverse
from rbbuild.package.component_specifier import ComponentSpecifier
from rbbuild.package.package import Package, PackageInstallAction


@dataclass
class DepsItems:
    namespace: str


class DepsParser:

    def __init__(
        self,
        platform: str,
        channel_factory: Callable[..., Channel],
        toolchain_factory: Callable[..., Toolchain],
    ):
        self.platform = platform
        self.channel_factory = channel_factory
        self.toolchain_factory = toolchain_factory


    # Walk over a normalized dependencies config list.
    # Each section dict may contain:
    #   deps              - list of dependency strings (mandatory)
    #   namespace         - installation namespace / sub-path in staging
    #   restrict_platform - skip section if the current platform does not match
    #   restrict_toolchain- skip section if the current toolchain does not match (fnmatch wildcard)
    #   <other keys>      - section-level attrs applied to every entry (e.g. build_only, traverse)
    #
    # Use rbbuild.deps.converter.deps_json_to_config() to convert legacy deps.json.
    def walk(self, dependencies_config: list) -> Iterator[Tuple[List[object], dict]]:
        for section in dependencies_config:
            if 'restrict_platform' in section:
                if section['restrict_platform'] != self.platform:
                    continue

            if 'restrict_toolchain' in section:
                current_tcid = str(self.toolchain_factory())
                if not fnmatch.fnmatch(current_tcid, section['restrict_toolchain']):
                    continue

            namespace = section.get('namespace', '')
            sec_attrs = {}
            if namespace:
                sec_attrs['installdir'] = namespace
                sec_attrs['namespace'] = namespace

            _skip = {'deps', 'namespace', 'restrict_platform', 'restrict_toolchain'}
            for key, value in section.items():
                if key in _skip:
                    continue
                # Convert TOML scalar non-strings (bool, int) to str for parse_attrs compatibility
                sec_attrs[key] = value if not isinstance(value, (bool, int, float)) else str(value)

            yield (section.get('deps', []), sec_attrs)


    def parse_attrs(self, item: Union[str, dict], sec_attrs: dict) -> Tuple[str, dict]:
        if type(item) is dict:
            if 'entry' in item:
                # New dict-entry format with optional SBOM override fields.
                # Section attributes are inherited; entry-level keys take precedence.
                attrs = copy(sec_attrs) if sec_attrs else {}
                attrs.update({k: v for k, v in item.items() if k != 'entry'})
                args0 = item['entry']
            elif 'name' in item:
                attrs = item
                args0 = item['name']
            else:
                raise SyntaxError(f'Invalid attributes (missing name or entry): {item!s}')
            return args0, attrs

        if type(item) is not str:
            raise SyntaxError(f'Invalid type for item ({type(item)})')

        # Separate "arg0" from "attr"
        args = item.split()
        arg0 = args[0]

        # Combine sec_attrs with attrs
        if sec_attrs:
            attrs = copy(sec_attrs)
        else:
            attrs = {}

        if len(args) > 1:
            for arg in args[1:]:
                if '=' in arg:
                    k,v = arg.split('=', maxsplit=1)
                else:
                    k = arg
                    v = None
                attrs[k] = v

        return arg0, attrs


    # This method breaks down a deps entry (e.g., a dependency in deps.json).
    # The expected form of an entry is:
    #
    #    [<channel>:]<pkgname>-<pkgversion>[ <attr>]*
    #    [<channel>:]<requirement>[ <attr>]*
    #    <url>[ <attr>]*
    #    <purl>[?<attr>[&<attr>]*
    #
    # with
    #
    #    <channel>             - Channel name
    #    <pkgname>             - Package name, accepted chars: [a-zA-Z0-9_]
    #    <pkgversion>          - Package version, accepted chars: any non-whitespace and ":"
    #    <requirement>         - Python Requirement specifier (PEP 508); with the option to specify
    #                            an exact non-wildcard version:
    #                              pkg==1.2.3.4
    #                            and the option to define a branch:
    #                              pkg[mybranch]==1.2.3.4 (same as: pkg-1.2.3.4 branch=mybranch)
    #    <attr>                - Attribute definition of the form
    #                            <flag>|<key>=<value>
    #                            Defined attrs:
    #                            build_only|traverse|installdir=<path>|
    #                            package_install_action=COPY|DEFAULT|channel=<name>|
    #                            toolchain=<name>|components=<name>[,<name>]*|
    #                            suffixes=<name>[,<name>]*|copyright=<name>|url=<url>|
    #                            purl=<purl>|branch=<name>|localversion=<name>
    #    <url>                 - a valid web URL starting with http:// or https://
    #    <purl>                - a valid PackageURL string, e.g.,
    #                              pkg:generic/mypkg@1.2.3.4?download_url=http://bosch.de/path/to/file
    #                              pkg:rbbuild/mypkg@1.2.3.4?channel=buildcore-develop&toolchain=linux-native

    def parse_item(self, item: Union[str, dict], sec_attrs: Dict[str,str]=None) -> Package:
        if type(item) is dict:
            item, sec_attrs = self.parse_attrs(item, sec_attrs)

        pkg = Package()
        attrs = {}
        channel = None

        if item.startswith('pkg:') or item.startswith('http://') or item.startswith('https://'):
            pkgstr, attrs = self.parse_attrs(item, sec_attrs)
            if not pkgstr:
                return None

            purl_parser = PURLParser()
            pkg.purl = purl_parser.parse(pkgstr, attrs)
            pkg.name = pkg.purl.name
            pkg.version = pkg.purl.version

            if pkg.purl.type == 'rbbuild':
                if not pkg.channel:
                    pkg.channel = self.channel_factory()
                if not pkg.toolchain:
                    pkg.toolchain = self.toolchain_factory()
            elif pkg.purl.type == 'generic':
                pkg.channel = self.channel_factory(name='url')

        else:
            if '#' in item:
                item, _ = item.split('#', maxsplit=1)

            item = item.strip()
            if not item:
                return None

            # Extract package name and version. Use cases:
            # - regular no version:        packagename
            # - regular with version (a):  packagename-1.2.3.4
            # - regular with version (b):  packagename-1.2.3.4
            # - with dash and version:     my-package-name@1.2.3.4
            # - with dash no version:      my-package-name@
            if '@' in item:
                arg0, rest = item.split('@', maxsplit=1)

                # extract channel from pkgstr if any
                if ':' in arg0:
                    channel, pkg.name = arg0.split(':', maxsplit=1)
                else:
                    pkg.name = arg0

                if rest:
                    pkg.version, attrs = self.parse_attrs(rest, sec_attrs)
                    if not item:
                        return None

            else:
                arg0, attrs = self.parse_attrs(item, sec_attrs)
                if not arg0:
                    return None

                # extract channel from package string, if any
                if ':' in arg0:
                    channel, arg0 = arg0.split(':', maxsplit=1)

                if '-' in arg0:
                    pkg.name, pkg.version = arg0.split('-', maxsplit=1)
                else:
                    self._extract_requirements_string(pkg, arg0)

        self._assign_rbbuild_attrs(pkg, attrs, channel=channel)

        return pkg


    # The package is a Python PEP 508 packaging "Requirement" string
    def _extract_requirements_string(self, pkg: Package, pkgstr: str):
        requirement = Requirement(pkgstr)
        pkg.name = requirement.name
        specifier = requirement.specifier

        # This is an exact match: pkg==1.0.0.0
        if len(requirement.specifier) == 1:
            spec = str(next(iter(requirement.specifier)))
            if spec.startswith('==') and '*' not in spec:
                _, pkg.version = spec.split('==', maxsplit=1)
                specifier = None

        pkg.version_constraints = specifier

        # We are abusing the PEP 508 syntax:
        # in rbbuild deps files, pkg[mybranch] specifies the branch name
        if len(requirement.extras) == 1:
            pkg.branch = next(iter(requirement.extras))


    def _parse_comp_spec(self, attrs: Dict[str, str]) -> ComponentSpecifier:
        value          = attrs.get('components') or attrs.get('component')
        components     = value.split(',') if value else None

        value          = attrs.get('suffixes') or attrs.get('suffix')
        suffixes       = value.split(',') if value else None

        build_only     = self._coerce_flag(attrs.get('build_only', '0'))
        traverse       = self._parse_traverse(attrs)

        return ComponentSpecifier( components=components,
                                   suffixes=suffixes,
                                   build_only=build_only,
                                   traverse=traverse )


    def _parse_traverse(self, attrs: dict) -> bool:
        traverse = None
        if 'traverse' in attrs:
            traverse = self._coerce_flag(attrs['traverse'])

        no_traverse = None
        if 'no_traverse' in attrs:
            no_traverse = self._coerce_flag(attrs['no_traverse'])

        return resolve_traverse(traverse, no_traverse)


    # These attributes can be a bare flag (None -> True), a string (deps-string
    # syntax, e.g. 'build_only=0') or a native bool (dict/TOML "entry" overrides).
    @staticmethod
    def _coerce_flag(value: Union[str, bool, None]) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        return ast.literal_eval(value)


    def _assign_rbbuild_attrs(self, pkg: Package, attrs: dict, channel: str):
        if pkg.branch and 'branch' in attrs:
            raise SyntaxError('Conflicting specification of branch')

        if channel:
            if 'channel' in attrs:
                raise SyntaxError('Conflicting specification of channel')

            attrs['channel'] = channel

        if 'channel' in attrs:
            chname = attrs.pop('channel')
            if chname:
                pkg.channel = self.channel_factory(name=chname)

        if 'toolchain' in attrs:
            tcid = attrs.pop('toolchain')
            if tcid:
                pkg.toolchain = self.toolchain_factory(tcid=tcid)

        # Check and assign attrs to package
        for key, value in attrs.items():
            if key in [ 'component', 'components',
                        'suffix', 'suffixes',
                        'build_only',
                        'traverse',
                        'no_traverse' ]:
                # This specifier allows setting certain attributes for components
                pkg.component_specifier = self._parse_comp_spec(attrs)

            elif key in ['package_install_action', 'install_action']:
                value = attrs.get('install_action') or attrs.get('package_install_action')
                pkg.install_action = PackageInstallAction.from_string(value)

            elif hasattr(pkg, key):
                setattr(pkg, key, value)

            else:
                raise SyntaxError(f'Invalid package attribute "{key}"')


    # Return tuple or package version strings (pkg_prev, pkg)
    def parse_deps_range(self, pkgstr: str) -> Tuple[str, str]:
        if '..' not in pkgstr:
            raise SyntaxError('Invalid input! Expected <package>..<package>')

        # lhs: left-hand side (=pkg_prev)
        # rhs: right-hand side (=pkg)
        lhs, rhs = pkgstr.split('..', maxsplit=1)

        # The legacy rbbuild syntax is in parts still allowed (except :: and wildcards)
        lhs_legacy, rhs_legacy = self._parse_deps_range_legacy(pkgstr)
        if lhs_legacy != lhs or rhs_legacy != rhs:
            return lhs_legacy, rhs_legacy

        # Simple form: pkg-1.0.0.0..2.0.0.0
        if '-' in lhs:
            pkgname, version = lhs.split('-', maxsplit=1)
            return lhs, f'{pkgname}-{rhs}'

        # Python 508 syntax
        req = Requirement(lhs)
        pkg_prev = str(req)
        # Case 1: pkg==1.0..2.0
        # --> implicit conversion: 2.0 becomes ==2.0
        if rhs[0].isdigit():
            rhs = f'=={rhs}'

        # Case 2: pkg==1.0..pkg==2.0
        # --> implicit conversion: allow full req strings on both sides
        # --> also allows use of branches, e.g: pkg[master]==1.0.0.0..pkg[hotfix_branch]
        if rhs[0].isalpha():
            req_rhs = Requirement(rhs)
            pkg = str(req_rhs)
        else:
            rhs_spec = SpecifierSet(rhs)
            pkg = f'{req.name}{rhs_spec}'

        return pkg_prev, pkg


    def _parse_deps_range_legacy(self, pkgstr: str) -> Tuple[str, str]:
        lhs, rhs = pkgstr.split('..', maxsplit=1)

        if '-' in lhs:
            # Full rbbuild version pattern, including channel prefix
            rbbuild_pattern = r'^((?:[\w-]+:)?\w+)\-((?:\d+)\.(?:\d+)\.(?:\d+))\-([\w\-_]+)\.(\d+)$'
            m_lhs = re.search(rbbuild_pattern, lhs)
            if not m_lhs:
                return lhs, rhs

            m_rhs = re.search(rbbuild_pattern, rhs)
            if not m_rhs:
                # Match legacy version against a regular version string (<M>.<m>.<b>.<B>),
                # optionally followed by a 5th "conflict" digit (<M>.<m>.<b>.<B>.<C>)
                # as produced by bump_conflict_version() on a publish conflict.
                # Example: 5.9.2903-develop.262..6.0.3014.0)
                m_rhs = re.search(r'^(\d+)\.(\d+)\.(\d+)\.(\d+)(?:\.\d+)?$', rhs)
                if m_rhs:
                    rhs = f'{m_lhs.group(1)}-{rhs}'
                else:
                    # Match <M>.<m>.<b>-<branch>.<B>
                    m_rhs = re.search(r'^((?:\d+)\.(?:\d+)\.(?:\d+))\-([\w\-_]+)\.(\d+)$', rhs)
                    if m_rhs:
                        rhs = f'{m_lhs.group(1)}-{m_rhs.group(1)}-{m_rhs.group(2)}.{m_rhs.group(3)}'
                    # Match <branch>.<B>
                    else:
                        m_rhs = re.search(r'^([\w\-_]+)\.(\d+)$', rhs)
                        if m_rhs:
                            rhs = f'{m_lhs.group(1)}-{m_lhs.group(2)}-{m_rhs.group(1)}.{m_rhs.group(2)}'
                        # Match <B>
                        else:
                            m_rhs = re.search(r'^(\d+)$', rhs)
                            if m_rhs:
                                rhs = f'{m_lhs.group(1)}-{m_lhs.group(2)}-{m_lhs.group(3)}.{m_rhs.group(1)}'
                            else:
                                raise SyntaxError(f'Invalid version input (rhs): {pkgstr}')

        return lhs, rhs


    # TODO: this method was used to allow variables in deps.json files.
    # The feature is currently not used.
    #def _expand_variables(self, var: str) -> str:
    #    variables = {
    #        '$PACKAGE_VERSION'  : str(self.metadata.version),
    #        '$PACKAGE_NAME'     : self.metadata.name,
    #        '$PACKAGE_MAJOR'    : self.metadata.major,
    #        '$PACKAGE_MINOR'    : self.metadata.minor,
    #        '$PACKAGE_REVISION' : self.metadata.revision,
    #        '$PACKAGE_BUILD'    : self.metadata.build,
    #        '$PACKAGE_BRANCH'   : self.metadata.branch,
    #    }
    #
    #    var = None
    #    for key, value in variables.items():
    #        if key in var:
    #            var = var.replace(key, str(value))
    #
    #    return var

