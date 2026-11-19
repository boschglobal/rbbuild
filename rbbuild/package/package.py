# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from dataclasses import dataclass
from enum import Enum
from packageurl import PackageURL
from packaging.specifiers import SpecifierSet
from typing import List, Union, Dict

from rbbuild.core.channel import Channel
from rbbuild.core.toolchain import Toolchain
from rbbuild.librbb.term import term
from rbbuild.package.component import Component
from rbbuild.package.license import License
from rbbuild.package.component_specifier import ComponentSpecifier
from rbbuild.package.type import PackageType


@dataclass
class ExternalReference:
    type: str
    url: str


@dataclass
class Tool:
    vendor: str  = None
    name: str    = None
    version: str = None
    external_references: List[ExternalReference] = None


class PackageInstallAction(Enum):
    DEFAULT = 0
    COPY    = 1

    def __str__(self):
        return self.name.lower()

    @classmethod
    def from_string(cls, value: str) -> 'PackageInstallAction':
        if value == 'default':
            return PackageInstallAction.DEFAULT
        elif value == 'copy':
            return PackageInstallAction.COPY

        raise SyntaxError(f'PackageInstallAction: Unknown install_action {value}')


@dataclass
class Supplier:
    name: str  = None
    email: str = None
    url: str   = None


# TODO: we could add more modeling options for the integration type
# see: https://spdx.github.io/spdx-spec/v2-draft/relationships-between-SPDX-elements/
# A good description is also found here:
# https://documentation.blackduck.com/bundle/bd-hub/page/Reporting/dependencyRelationshipsInSbomReports.html
class IntegrationType(Enum):
    STATIC_LINK  = 0
    DYNAMIC_LINK = 1
    OTHER        = 2    # separate executable
    CONTAINS     = 3    # embedded from source code


    def __str__(self):
        return self.name.lower()


    @classmethod
    def from_string(cls, value: str) -> 'IntegrationType':
        return getattr(cls, value.upper())


# Deps.json package entry representation.
class Package:
    def __init__(self, name: str=None, version: str=None):
        self.name: str                               = name
        self.version: str                            = version
        self.channel: Channel                        = None
        self.toolchain: Toolchain                    = None
        self.dependencies: Dict[str, 'Package']      = {}
        self.manifest: Component                     = None
        self.components: List[Component]             = []
        self.installdir: str                         = ''
        self.namespace: str                          = ''
        # This flag is set if this object was constructed from a manifest.json.
        # For example, Package objects without manifests are created by
        # DepsParser.parse_item() or RepositoryManager.search_versions() calls.
        self.manifest_loaded: bool                   = False
        self.git_hash: str                           = None
        self.git_repo: str                           = None
        self.build_url: str                          = None
        self.component_specifier: ComponentSpecifier = None
        self.install_action: PackageInstallAction    = PackageInstallAction.DEFAULT

        self.copyright: str                          = None
        self.cpe: str                                = None

        self._version_constraints: SpecifierSet      = None   # Python PEP 508 constraints, e.g., >1.0
        self.branch                                  = None
        self.localversion: str                       = None
        self._purl                                   = None
        self.url                                     = None
        self._licenses: List[License]                = []
        self._component_type: PackageType            = PackageType.APPLICATION
        self.ancestors: List[str]                    = None
        self._supplier: Supplier                     = None
        self._integration_type: IntegrationType      = None
        self.tools: List[Tool]                       = []


    @property
    def version_constraints(self) -> SpecifierSet:
        return self._version_constraints


    @version_constraints.setter
    def version_constraints(self, value: Union[SpecifierSet, str]):
        if value is None:
            self._version_constraints = None
        elif type(value) is SpecifierSet:
            self._version_constraints = value
        elif type(value) is str:
            self._version_constraints = SpecifierSet(value)
        else:
            raise SyntaxError(f'Package.version_constraints: Invalid type "{type(value)}". Expected string or SpecifierSet: {str(value)}')


    #
    # Meta data (input SBOM)
    #

    @property
    def license(self) -> License:
        licenses = self.licenses
        if licenses and len(licenses) > 0:
            return licenses[0]


    @license.setter
    def license(self, value):
        self._licenses = License.coerce(value)


    @property
    def licenses(self) -> List[License]:
        return self._licenses

    @licenses.setter
    def licenses(self, value):
        self._licenses = License.coerce(value)


    @property
    def component_type(self) -> 'PackageType':
        return self._component_type

    @component_type.setter
    def component_type(self, value):
        if isinstance(value, PackageType):
            self._component_type = value
        else:
            self._component_type = PackageType.from_string(value)


    @property
    def integration_type(self) -> 'IntegrationType':
        return self._integration_type

    @integration_type.setter
    def integration_type(self, value):
        if value is None or isinstance(value, IntegrationType):
            self._integration_type = value
        else:
            self._integration_type = IntegrationType.from_string(value)


    @property
    def supplier(self) -> 'Supplier':
        return self._supplier

    @supplier.setter
    def supplier(self, value):
        if value is None or isinstance(value, Supplier):
            self._supplier = value
        elif isinstance(value, dict):
            self._supplier = Supplier(**value)
        else:
            self._supplier = value


    #
    # PackageURL: pkg:<type>/<profile>/<pkg>@<version>[#<subpath][?<qualifier>&<qualifier>...]
    #
    @property
    def purl(self) -> PackageURL:
        return self._purl


    @purl.setter
    def purl(self, value: Union[PackageURL, str]):
        if type(value) is PackageURL:
            self._purl = value
        elif type(value) is str:
            self._purl = PackageURL.from_string(value)
        else:
            raise SyntaxError('Package.purl: Invalid type {type(value)}. Expected string or PackageURL')


    #
    # dunder methods - str(), repr(), eq()
    #

    # Identification of deps Package objects (also stored in manifest.json):
    #
    #    [<namespace>/]<pkgname>[@<toolchain>]
    #
    # With:
    #   <namespace>              package namespace (if not empty)
    #   <pkgname>                package name
    def __repr__(self):
        pkgstr = ''
        if self.installdir:
            pkgstr += self.installdir + '/'

        if self.name:
            pkgstr += self.name

        if self.toolchain:
            pkgstr += f'@{self.toolchain}'

        return pkgstr


    # String representation of Package objects (e.g., in outputs or logs)
    #
    #    [<namespace>/]<pkgname>[-<version>]
    #
    # With:
    #   <namespace>              package namespace (if not empty)
    #   <pkgname>                package name
    #   <version>                package version (only if not empty)
    def __str__(self):
        pkgstr = ''

        if self.name:
            pkgstr = self.name

        if self.version:
            # '@' disambiguates the version from a name that itself
            # contains dashes (e.g. "my-package@1.0.0") - DepsParser.
            # parse_item() only splits plain "name-version" strings on
            # their first dash, so a dashed name would otherwise be
            # mis-parsed on the next round-trip.
            separator = '@' if '-' in (self.name or '') else '-'
            pkgstr += separator + self.version

        return pkgstr


    # We consider two Package objects the same if their
    # string representation is the same.
    def __eq__(self, other):
        return str(self) == str(other)


    #
    # Helper methods
    #

    def merge(self, other: 'Package'):
        # Version
        if self.version != other.version:
            # This is actually allowed:
            #
            #   pkg         components=dev        build_only
            #   pkg-1.2.3.4 components=bla,blubb
            #
            if not self.version:
                self.version = other.version
            elif not other.version:
                pass
            else:
                raise RuntimeError(f'Version mismatch detected. Failed to merge package {term.bright_white(other.version)} into {term.bright_white(self.version)}')

        if self.branch != other.branch:
            if not self.branch:
                self.branch = other.branch
            elif not other.branch:
                pass
            else:
                raise RuntimeError(f'Branch mismatch detected. Failed to merge package {term.bright_white(other.branch)} into {term.bright_white(self.branch)}')

        if self.localversion != other.localversion:
            if not self.localversion:
                self.localversion = other.localversion
            elif not other.localversion:
                pass
            else:
                raise RuntimeError(f'Local version mismatch detected. Failed to merge package {term.bright_white(other.localversion)} into {term.bright_white(self.localversion)}')

        # version_constraints
        if not self.version_constraints:
            self.version_constraints = other.version_constraints
        elif other.version_constraints:
            self.version_constraints &= other.version_constraints

        # TODO: ComponentSpecifier (Query params)
        #for key, attrs in other.query_param.items.items():
        #    for attr, attr_value in attrs.items():
        #        if self.query_param.check(key[0], key[1], attr) is False:
        #            self.query_param.items.add(key[0], key[1], {attr: attr_value})

        # Merge dependencies
        if other.dependencies:
            for name, child in other.dependencies.items():
                if name not in self.dependencies:
                    self.dependencies[name] = other.dependencies[name]
                else:
                    self.dependencies[name].merge(other.dependencies[name])

        # Merge components
        if other.components:
            for comp in other.components:
                found = False
                for pcomp in self.components:
                    if pcomp == comp:
                        found = True
                        if comp.build_only is True:
                            pcomp.build_only = True
                        break
                if found is False:
                    self.components.append(comp)

        # Merge metadata from other into self
        self.licenses.extend(other.licenses)
        self.licenses = list(set(self.licenses))  # deduplicate
        self.component_type = other.component_type
        if self.ancestors is None:
            self.ancestors = other.ancestors
        if self.supplier is None:
            self.supplier = other.supplier
        if self.integration_type is None:
            self.integration_type = other.integration_type
        if not self.tools:
            self.tools = other.tools


    @property
    def build_only(self) -> bool:
        build_only = True                   # will switch to False if any component is build_only=False
        for comp in self.components:
            if comp.build_only is False:
                build_only = False

        return build_only


    @build_only.setter
    def build_only(self, value: bool):
        for comp in self.components:
            comp.build_only = value


    @property
    def traverse(self) -> bool:
        traverse = True                     # will switch to False if any component is traverse=False
        for comp in self.components:
            if comp.traverse is False:
                traverse = False

        return traverse
