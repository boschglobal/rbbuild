# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest

from rbbuild.package.license import License
from rbbuild.package.component import Component
from rbbuild.package.component_specifier import ComponentSpecifier
from rbbuild.package.package import Package, PackageInstallAction, IntegrationType, Supplier, Tool
from rbbuild.service.issuetracker.issuetracker_manager import Issue

# Unit tests for rbbuild.package — License, Component, ComponentSpecifier, Package.


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------

def test_license_by_id():
    lic = License(id='MIT')
    assert lic.id == 'MIT'
    assert lic.name is None
    assert lic.expression is None


def test_license_by_name():
    lic = License(name='My Custom License')
    assert lic.name == 'My Custom License'
    assert lic.id is None


def test_license_must_have_id_or_name():
    with pytest.raises(SyntaxError):
        License()


def test_license_cannot_have_both_id_and_name():
    with pytest.raises(SyntaxError):
        License(id='MIT', name='also MIT')


def test_license_expression():
    lic = License(expression='MIT OR Apache-2.0')
    assert lic.expression == 'MIT OR Apache-2.0'
    assert lic.id is None


def test_license_expression_with_acknowledgement():
    lic = License(expression='GPL-2.0', acknowledgement='expressed')
    assert lic.acknowledgement == 'expressed'


def test_license_expression_rejects_extra_keys():
    with pytest.raises(SyntaxError):
        License(expression='MIT', url='http://example.com')


def test_license_id_with_optional_fields():
    lic = License(id='MIT', acknowledgement='declared', url='https://spdx.org/licenses/MIT.html',
                  text={'content': 'text', 'contentType': 'text/plain'})
    assert lic.acknowledgement == 'declared'
    assert lic.url == 'https://spdx.org/licenses/MIT.html'
    assert lic.text == {'content': 'text', 'contentType': 'text/plain'}


def test_license_id_rejects_unknown_key():
    with pytest.raises(TypeError):
        License(id='MIT', unknown_key='value')


def test_license_to_dict_id():
    lic = License(id='MIT')
    d = lic.to_dict()
    assert d == {'license': {'id': 'MIT'}}


def test_license_to_dict_name():
    lic = License(name='Custom', url='http://example.com')
    d = lic.to_dict()
    assert d == {'license': {'name': 'Custom', 'url': 'http://example.com'}}


def test_license_to_dict_expression():
    lic = License(expression='MIT OR Apache-2.0')
    d = lic.to_dict()
    assert d == {'expression': 'MIT OR Apache-2.0'}


def test_license_to_dict_expression_with_acknowledgement():
    lic = License(expression='MIT', acknowledgement='expressed')
    d = lic.to_dict()
    assert d == {'expression': 'MIT', 'acknowledgement': 'expressed'}


def test_license_properties_field():
    lic = License(id='MIT', properties={'key': 'value'})
    assert lic.properties == {'key': 'value'}


def test_license_properties_invalid_type():
    with pytest.raises(SyntaxError):
        License(id='MIT', properties='not-a-dict')


def test_license_licensing_field():
    lic = License(id='MIT', licensing={'mode': 'strict'})
    assert lic.licensing == {'mode': 'strict'}


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

def test_component_basic():
    c = Component(name='prod', suffix='tar.xz', filename='mypkg-1.0-linux-native-prod.tar.xz')
    assert c.name == 'prod'
    assert c.suffix == 'tar.xz'
    assert c.filename == 'mypkg-1.0-linux-native-prod.tar.xz'
    assert c.build_only is False
    assert c.traverse is True


def test_component_equality():
    c1 = Component(name='prod', suffix='tar.xz', filename='a.tar.xz')
    c2 = Component(name='prod', suffix='tar.xz', filename='b.tar.xz')  # filename not in equality
    c3 = Component(name='dev',  suffix='tar.xz', filename='a.tar.xz')
    assert c1 == c2
    assert c1 != c3


def test_component_hash():
    c1 = Component(name='prod', suffix='tar.xz')
    c2 = Component(name='prod', suffix='tar.xz')
    assert hash(c1) == hash(c2)


def test_component_build_only():
    c = Component(name='sbom', suffix='json', build_only=True)
    assert c.build_only is True


# ---------------------------------------------------------------------------
# ComponentSpecifier
# ---------------------------------------------------------------------------

def test_component_specifier_explicit():
    cs = ComponentSpecifier(components=['prod'], suffixes=['tar.xz'], build_only=False, traverse=True)
    assert cs.check('prod', 'tar.xz', None) is True
    assert cs.check('dev', 'tar.xz', None) is None


def test_component_specifier_wildcard_component():
    cs = ComponentSpecifier(components=None, suffixes=None, build_only=True, traverse=True)
    assert cs.check('prod', 'tar.xz', None) is True
    assert cs.check('anything', 'rpm', 'build_only') is True


def test_component_specifier_component_only():
    cs = ComponentSpecifier(components=['prod', 'dev'], suffixes=None, build_only=False, traverse=True)
    assert cs.check('prod', 'tar.xz', None) is True
    assert cs.check('dev',  'rpm',    None) is True
    assert cs.check('sbom', 'json',   None) is None


def test_component_specifier_items():
    cs = ComponentSpecifier(components=['prod'], suffixes=None, build_only=False, traverse=True)
    assert ('prod', None) in cs.items


def test_component_specifier_attr_check():
    cs = ComponentSpecifier(components=None, suffixes=None, build_only=True, traverse=False)
    assert cs.check('any', 'any', 'build_only') is True
    assert cs.check('any', 'any', 'traverse') is False


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------

def test_package_basic():
    pkg = Package(name='mypkg', version='1.0.0')
    assert pkg.name == 'mypkg'
    assert pkg.version == '1.0.0'


def test_package_version_constraints_from_string():
    pkg = Package(name='mypkg')
    pkg.version_constraints = '>=1.0,<2.0'
    assert '1.5' in pkg.version_constraints


def test_package_version_constraints_none():
    pkg = Package(name='mypkg')
    pkg.version_constraints = None
    assert pkg.version_constraints is None


def test_package_version_constraints_invalid_type():
    pkg = Package(name='mypkg')
    with pytest.raises(SyntaxError):
        pkg.version_constraints = 12345


def test_package_license_str_shorthand():
    pkg = Package(name='mypkg')
    pkg.licenses = License.coerce('MIT')
    assert len(pkg.licenses) == 1
    assert pkg.licenses[0].expression == 'MIT'


def test_package_license_list():
    pkg = Package(name='mypkg')
    pkg.licenses = License.coerce([{'license': {'id': 'MIT'}}])
    assert pkg.licenses[0].id == 'MIT'


def test_package_license_property():
    pkg = Package(name='mypkg')
    pkg.licenses = License.coerce('Apache-2.0')
    assert pkg.license.expression == 'Apache-2.0'


def test_package_license_clear():
    pkg = Package(name='mypkg')
    pkg.licenses = License.coerce('MIT')
    pkg.licenses = None
    assert pkg.licenses is None


def test_package_branch_abbreviated():
    assert Issue.branch_abbreviated('PROJ-1234-some-long-branch-name') == 'PROJ-1234'


def test_package_branch_abbreviated_none():
    assert Issue.branch_abbreviated(None) is None


def test_package_install_action_default():
    pkg = Package(name='mypkg')
    assert pkg.install_action == PackageInstallAction.DEFAULT


def test_package_install_action_from_string():
    assert PackageInstallAction.from_string('copy') == PackageInstallAction.COPY
    assert PackageInstallAction.from_string('default') == PackageInstallAction.DEFAULT


def test_package_install_action_invalid():
    with pytest.raises(SyntaxError):
        PackageInstallAction.from_string('invalid')


def test_integration_type_str():
    assert str(IntegrationType.STATIC_LINK) == 'static_link'
    assert str(IntegrationType.DYNAMIC_LINK) == 'dynamic_link'


def test_integration_type_from_string():
    assert IntegrationType.from_string('STATIC_LINK') == IntegrationType.STATIC_LINK
    assert IntegrationType.from_string('OTHER') == IntegrationType.OTHER


def test_package_str_with_version():
    pkg = Package(name='mypkg', version='1.0.0')
    assert str(pkg) == 'mypkg-1.0.0'


def test_package_str_no_version():
    pkg = Package(name='mypkg')
    assert str(pkg) == 'mypkg'


def test_package_repr_no_toolchain():
    pkg = Package(name='mypkg', version='1.0.0')
    assert repr(pkg) == 'mypkg'


def test_package_repr_with_installdir():
    pkg = Package(name='mypkg')
    pkg.installdir = 'subdir'
    assert repr(pkg) == 'subdir/mypkg'


# ---------------------------------------------------------------------------
# PackageInstallAction str
# ---------------------------------------------------------------------------

def test_package_install_action_str():
    assert str(PackageInstallAction.DEFAULT) == 'default'
    assert str(PackageInstallAction.COPY) == 'copy'


# ---------------------------------------------------------------------------
# Package.purl setter
# ---------------------------------------------------------------------------

def test_package_purl_setter_string():
    from packageurl import PackageURL
    pkg = Package(name='mypkg')
    pkg.purl = 'pkg:rbbuild/mypkg@1.0.0'
    assert pkg.purl == PackageURL.from_string('pkg:rbbuild/mypkg@1.0.0')


def test_package_purl_setter_purl_object():
    from packageurl import PackageURL
    purl = PackageURL.from_string('pkg:rbbuild/mypkg@1.0.0')
    pkg = Package(name='mypkg')
    pkg.purl = purl
    assert pkg.purl == purl


def test_package_purl_setter_invalid():
    pkg = Package(name='mypkg')
    with pytest.raises(SyntaxError):
        pkg.purl = 12345


# ---------------------------------------------------------------------------
# Package.ancestors
# ---------------------------------------------------------------------------

def test_package_ancestors_from_list():
    pkg = Package(name='mypkg')
    pkg.ancestors = ['ancestor1', 'ancestor2']
    assert pkg.ancestors == ['ancestor1', 'ancestor2']


def test_package_ancestors_clear():
    pkg = Package(name='mypkg')
    pkg.ancestors = ['ancestor1']
    pkg.ancestors = None
    assert pkg.ancestors is None


# ---------------------------------------------------------------------------
# Package.supplier
# ---------------------------------------------------------------------------

def test_package_supplier_from_dict():
    # Supplier is a plain dataclass constructor
    pkg = Package(name='mypkg')
    pkg.supplier = Supplier(name='ACME', email='info@acme.com', url='https://acme.com')
    assert pkg.supplier.name == 'ACME'
    assert pkg.supplier.email == 'info@acme.com'


# ---------------------------------------------------------------------------
# Package.integration_type
# ---------------------------------------------------------------------------

def test_package_integration_type_assignment():
    pkg = Package(name='mypkg')
    pkg.integration_type = IntegrationType.STATIC_LINK
    assert pkg.integration_type == IntegrationType.STATIC_LINK


# ---------------------------------------------------------------------------
# Package.tools
# ---------------------------------------------------------------------------

def test_package_tools_from_dict():
    # Tool is a plain dataclass constructor
    pkg = Package(name='mypkg')
    pkg.tools = [Tool(vendor='ACME', name='mytool', version='1.0')]
    assert len(pkg.tools) == 1
    assert pkg.tools[0].vendor == 'ACME'


# ---------------------------------------------------------------------------
# Package.build_only / traverse
# ---------------------------------------------------------------------------

def test_package_build_only_all_build_only():
    from rbbuild.package.component import Component
    pkg = Package(name='mypkg')
    pkg.components = [Component(name='sbom', suffix='json', build_only=True)]
    assert pkg.build_only is True


def test_package_build_only_mixed():
    from rbbuild.package.component import Component
    pkg = Package(name='mypkg')
    pkg.components = [
        Component(name='prod', suffix='tar.xz', build_only=False),
        Component(name='sbom', suffix='json', build_only=True),
    ]
    assert pkg.build_only is False


def test_package_traverse_default():
    from rbbuild.package.component import Component
    pkg = Package(name='mypkg')
    pkg.components = [Component(name='prod', suffix='tar.xz')]
    assert pkg.traverse is True


def test_package_traverse_false():
    from rbbuild.package.component import Component
    pkg = Package(name='mypkg')
    pkg.components = [Component(name='prod', suffix='tar.xz', traverse=False)]
    assert pkg.traverse is False


# ---------------------------------------------------------------------------
# Package.merge
# ---------------------------------------------------------------------------

def test_package_merge_basic():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='mypkg', version='1.0.0')
    pkg2.licenses = License.coerce('MIT')
    pkg1.merge(pkg2)
    assert pkg1.licenses[0].expression == 'MIT'


def test_package_merge_version_missing_on_self():
    pkg1 = Package(name='mypkg')
    pkg2 = Package(name='mypkg', version='1.0.0')
    pkg1.merge(pkg2)
    assert pkg1.version == '1.0.0'


def test_package_merge_version_mismatch_raises():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='mypkg', version='2.0.0')
    with pytest.raises(RuntimeError, match='Version mismatch'):
        pkg1.merge(pkg2)


def test_package_merge_dependencies():
    parent1 = Package(name='parent', version='1.0.0')
    parent2 = Package(name='parent', version='1.0.0')
    child = Package(name='child', version='0.1.0')
    parent2.dependencies = {'child': child}
    parent1.merge(parent2)
    assert 'child' in parent1.dependencies


def test_package_merge_components():
    from rbbuild.package.component import Component
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='mypkg', version='1.0.0')
    comp = Component(name='prod', suffix='tar.xz', filename='f.tar.xz')
    pkg2.components = [comp]
    pkg1.merge(pkg2)
    assert len(pkg1.components) == 1
    assert pkg1.components[0].name == 'prod'


def test_package_merge_branch_missing_on_self():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg2 = Package(name='mypkg', version='1.0.0')
    pkg2.branch = 'main'
    pkg1.merge(pkg2)
    assert pkg1.branch == 'main'


def test_package_merge_branch_mismatch_raises():
    pkg1 = Package(name='mypkg', version='1.0.0')
    pkg1.branch = 'develop'
    pkg2 = Package(name='mypkg', version='1.0.0')
    pkg2.branch = 'main'
    with pytest.raises(RuntimeError, match='Branch mismatch'):
        pkg1.merge(pkg2)


def test_package_merge_version_constraints():
    pkg1 = Package(name='mypkg')
    pkg1.version_constraints = '>=1.0'
    pkg2 = Package(name='mypkg')
    pkg2.version_constraints = '<2.0'
    pkg1.merge(pkg2)
    assert '1.5' in pkg1.version_constraints
    assert '2.1' not in pkg1.version_constraints


def test_package_merge_localversion_missing_on_self():
    pkg1 = Package(name='mypkg')
    pkg2 = Package(name='mypkg')
    pkg2.localversion = 'rbbuild.1234'
    pkg1.merge(pkg2)
    assert pkg1.localversion == 'rbbuild.1234'


def test_package_merge_localversion_mismatch_raises():
    pkg1 = Package(name='mypkg')
    pkg1.localversion = 'rbbuild.1234'
    pkg2 = Package(name='mypkg')
    pkg2.localversion = 'rbbuild.5678'
    with pytest.raises(RuntimeError, match='Local version mismatch'):
        pkg1.merge(pkg2)
