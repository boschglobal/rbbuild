# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import base64
import hashlib
import io
import re
import tarfile
import tomllib
import zipfile

from pathlib import Path


# Tarfile filter that removes __pycache__ directories and their contents.
def _pycache_filter(tarinfo):
    return None if '__pycache__' in Path(tarinfo.name).parts else tarinfo


# Validates config_settings and returns (pypa, cname, comp, multi_wheel).
def _get_config(config_settings):
    if not config_settings or 'rbbuild_python_backend' not in config_settings:
        raise NotImplementedError('This build backend only works with rbbuild!')
    return (
        config_settings['rbbuild_python_backend'],
        config_settings['package_name'],
        config_settings['packaging_entry'],
        config_settings['multi_wheel'],
    )


# Returns the urlsafe-base64-encoded SHA-256 digest of data (no padding).
def _sha256_digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()


# Extension modules carry the interpreter in their file name, e.g.,
#   _x.cpython-312-x86_64-linux-gnu.so, _x.cp312-win_amd64.pyd (CPython)
#   _x.pypy310-pp73-x86_64-linux-gnu.so (PyPy)
_CPYTHON_MODULE = re.compile(r'\.(?:cpython-(\d)(\d+)[^.]*\.so|cp(\d)(\d+)-[^.]*\.pyd)$')
_PYPY_MODULE    = re.compile(r'\.pypy(\d)(\d+)-(pp\d+)-[^.]*\.(?:so|pyd)$')
_ABI3_MODULE    = re.compile(r'\.abi3\.(?:so|pyd)$')


# Returns "<python tag>-<abi tag>" of an extension module, or None.
def _extension_module_tag(filename: str):
    if m := _CPYTHON_MODULE.search(filename):
        tag = f'cp{m.group(1) or m.group(3)}{m.group(2) or m.group(4)}'
        return f'{tag}-{tag}'
    if m := _PYPY_MODULE.search(filename):
        version = f'{m.group(1)}{m.group(2)}'
        return f'pp{version}-pypy{version}_{m.group(3)}'
    return None


# Returns "py3-none", or the tag of the extension modules in the wheel.
def _python_abi_tag(cname: str, arcnames: list) -> str:
    tags = set()
    for arcname in arcnames:
        filename = Path(arcname).name
        if _ABI3_MODULE.search(filename):
            raise SyntaxError(f'[packaging.{cname}]: abi3 extension {filename} is not supported. Set "wheel-tag" explicitly.')
        if tag := _extension_module_tag(filename):
            tags.add(tag)

    if len(tags) > 1:
        raise SyntaxError(f'[packaging.{cname}]: extension modules for several Python versions: {", ".join(sorted(tags))}')
    return tags.pop() if tags else 'py3-none'


# Returns (compatibility tag, is_purelib) of the wheel of a packaging entry.
def _wheel_tag(cname: str, comp: dict, toolchain, arcnames: list) -> tuple:
    if not comp.get('platform_specific'):
        if 'wheel_tag' in comp:
            raise SyntaxError(f'[packaging.{cname}]: "wheel-tag" requires "platform-specific = true"')
        return 'py3-none-any', True

    if comp.get('wheel_tag'):
        return comp['wheel_tag'], False

    platform_tag = toolchain.wheel_platform_tag if toolchain else None
    if not platform_tag:
        raise SyntaxError(
            f'[packaging.{cname}]: toolchain {toolchain} defines no wheel platform tag. '
            f'Select a toolchain with -t, define the tag in the toolchain definition, or set "wheel-tag" explicitly.'
        )

    return f'{_python_abi_tag(cname, arcnames)}-{platform_tag}', False


# Builds entry_points.txt content for [project.scripts],
# [project.gui-scripts] and [project.entry-points.<group>] (PEP 427 /
# entry-points spec). A packaging entry's own 'entry-points' list of
# {group, name, value} tables is merged on top, so that wheels of a
# multi-wheel project can differ. It is a list because the configuration
# loader rewrites '.' and '-' in dict keys (i.e., in group names).
def _build_entry_points_txt(pyproject_toml: dict, comp: dict = None) -> bytes:
    project = pyproject_toml.get('project', {})

    groups = {
        'console_scripts': dict(project.get('scripts', {})),
        'gui_scripts':     dict(project.get('gui-scripts', {})),
    }
    for group, entries in project.get('entry-points', {}).items():
        groups.setdefault(group, {}).update(entries)
    for ep in (comp or {}).get('entry_points', []):
        if not isinstance(ep, dict) or not {'group', 'name', 'value'} <= ep.keys():
            raise SyntaxError('[packaging]: entry-points items need "group", "name", and "value"')
        groups.setdefault(ep['group'], {})[ep['name']] = ep['value']

    ep_lines = []
    for group, entries in groups.items():
        if not entries:
            continue
        if ep_lines:
            ep_lines.append('')
        ep_lines.append(f'[{group}]')
        for ep_name, ep_ref in entries.items():
            ep_lines.append(f'{ep_name} = {ep_ref}')

    if not ep_lines:
        return None

    return ('\n'.join(ep_lines) + '\n').encode('utf-8')


# Returns the Requires-Dist list: [project] dependencies plus exact pins to
# the python components named in the entry's 'depends-on' (string or list).
def _wheel_requirements(pypa, cname: str, comp: dict, version: str) -> list:
    depends_on = comp.get('depends_on')
    if not depends_on:
        return pypa.requirements
    if isinstance(depends_on, str):
        depends_on = [depends_on]

    python_entries = {n for n, c in pypa.packaging.items() if c.get('type') == 'python'}
    pins = []
    for dep in depends_on:
        dep_key = re.sub(r'[-.]+', '_', dep).lower()
        if dep_key == cname:
            raise SyntaxError(f'[packaging.{cname}]: depends-on must not refer to itself')
        if dep_key not in python_entries:
            raise SyntaxError(f'[packaging.{cname}]: depends-on entry "{dep}" is not a python packaging entry')
        pins.append(f'{pypa.metadata.name}_{dep_key}=={version}')
    return [*pypa.requirements, *pins]


# Minimal metadata adapter matching the interface _generate_pkg_info()
# expects from a rich Metadata object, built from a plain [project] table.
# Used by build_editable(), which - unlike build_wheel()/build_sdist() -
# has no PyPA instance available (see build_editable() below).
class _ProjectMetadata:
    def __init__(self, project: dict):
        self.config = {'description': project.get('description', '')}
        self.authors = project.get('authors', [])
        self.maintainers = project.get('maintainers', [])
        self.license = project.get('license', '')


def build_sdist(sdist_directory, config_settings=None):
    pypa, cname, comp, multi_wheel = _get_config(config_settings)

    sdist_directory = Path(sdist_directory)
    name            = pypa.metadata.name
    if multi_wheel:
        name += f'_{cname}'
    version         = str(pypa.metadata.version)
    archive_prefix  = f'{name}-{version}'
    sdist_path      = sdist_directory / f'{archive_prefix}.tar.gz'

    files       = pypa.packaging.resolve_files(cname, comp)
    shared_data = pypa.packaging.resolve_shared_data(cname, comp)

    pkg_info_bytes = _generate_pkg_info(
        name, version, pypa.metadata, _wheel_requirements(pypa, cname, comp, version),
        pypa.optional_requirements,
        pypa.pyproject_toml.get('project', {}), pypa.paths.source,
    ).encode('utf-8')

    with tarfile.open(sdist_path, 'w:gz') as tar:
        info = tarfile.TarInfo(name=f'{archive_prefix}/PKG-INFO')
        info.size = len(pkg_info_bytes)
        tar.addfile(info, io.BytesIO(pkg_info_bytes))

        # sdist stores every source file at its original path; strip/dest are
        # wheel-only concerns and must not be applied here so that pip can
        # resolve the same src patterns when building a wheel from the sdist
        for fname, _strip, _dest in [*files, *shared_data]:
            tar.add(fname, arcname=str(Path(archive_prefix) / fname), filter=_pycache_filter)

    return sdist_path.name


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    pypa, cname, comp, multi_wheel = _get_config(config_settings)

    wheel_directory = Path(wheel_directory)
    name      = pypa.metadata.name
    if multi_wheel:
        name += f'_{cname}'
    version   = str(pypa.metadata.version)
    dist_info = f'{name}-{version}.dist-info'
    data_dir  = f'{name}-{version}.data'

    files       = pypa.packaging.resolve_files(cname, comp)
    excluded    = pypa.packaging.resolve_excluded(comp)
    shared_data = pypa.packaging.resolve_shared_data(cname, comp)

    entries = []
    for fname, strip, dest in files:
        for item in (sorted(fname.rglob('*')) if fname.is_dir() else [fname]):
            if item.is_dir() or '__pycache__' in item.parts or item in excluded:
                continue
            rel = item.relative_to(strip) if strip else item
            entries.append((item, (Path(dest) / rel).as_posix() if dest else rel.as_posix()))

    wheel_tag, purelib = _wheel_tag(
        cname, comp, config_settings.get('toolchain'), [arcname for _, arcname in entries])
    whl_path  = wheel_directory / f'{name}-{version}-{wheel_tag}.whl'

    metadata_bytes = _generate_pkg_info(
        name, version, pypa.metadata, _wheel_requirements(pypa, cname, comp, version),
        pypa.optional_requirements,
        pypa.pyproject_toml.get('project', {}), pypa.paths.source,
    ).encode('utf-8')
    wheel_bytes = (
        'Wheel-Version: 1.0\n'
        'Generator: rbbuild\n'
        f'Root-Is-Purelib: {"true" if purelib else "false"}\n'
        f'Tag: {wheel_tag}\n'
    ).encode('utf-8')

    record_rows = []

    with zipfile.ZipFile(whl_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for item, arcname in entries:
            zf.write(item, arcname)
            record_rows.append(f'{arcname},sha256={_sha256_digest(item.read_bytes())},{item.stat().st_size}')

        for fname, strip, dest in shared_data:
            for item in (sorted(fname.rglob('*')) if fname.is_dir() else [fname]):
                if item.is_dir():
                    continue
                rel     = item.relative_to(strip) if strip else item
                arcname = (Path(data_dir) / 'data' / dest / rel).as_posix() if dest else (Path(data_dir) / 'data' / rel).as_posix()
                zf.write(item, arcname)
                record_rows.append(f'{arcname},sha256={_sha256_digest(item.read_bytes())},{item.stat().st_size}')

        for arcname, data in [
            (f'{dist_info}/WHEEL',    wheel_bytes),
            (f'{dist_info}/METADATA', metadata_bytes),
        ]:
            zf.writestr(arcname, data)
            record_rows.append(f'{arcname},sha256={_sha256_digest(data)},{len(data)}')

        # entry_points.txt (PEP 427 / entry-points spec)
        ep_bytes = _build_entry_points_txt(pypa.pyproject_toml, comp)
        if ep_bytes:
            arcname = f'{dist_info}/entry_points.txt'
            zf.writestr(arcname, ep_bytes)
            record_rows.append(f'{arcname},sha256={_sha256_digest(ep_bytes)},{len(ep_bytes)}')

        # RECORD has no hash entry for itself (PEP 427)
        zf.writestr(f'{dist_info}/RECORD', '\n'.join(record_rows) + f'\n{dist_info}/RECORD,,\n')

    return whl_path.name


# PEP 660 editable-install hook, e.g. `uv pip install -e . --group dev` /
# `pip install -e .` for rbbuild's own developer setup.
#
# Unlike build_wheel()/build_sdist(), this is invoked by an external PEP 517
# frontend (pip/uv/build) via the standard subprocess-based hook protocol, so
# there is no rich PyPA instance available in config_settings - only plain,
# JSON-serializable data (here: none at all). It therefore reads
# pyproject.toml directly from the current directory, which PEP 517
# guarantees is the project root, and produces the simplest valid editable
# wheel: a .pth file that adds the project root to sys.path, so `import
# rbbuild` resolves to this checkout (same mechanism already relied on by
# [tool.pytest.ini_options] pythonpath = '.').
#
# This intentionally does not reuse resolve_files()/resolve_shared_data()
# (multi-component wheel splitting, shared-data, etc.) - those are release-
# packaging concerns handled by `rbbuild -p` via build_wheel() directly;
# an editable install only needs to make the package importable for
# development.
def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    wheel_directory = Path(wheel_directory)
    project_root = Path.cwd()

    with open(project_root / 'pyproject.toml', 'rb') as fd:
        pyproject_toml = tomllib.load(fd)
    project = pyproject_toml.get('project', {})

    name      = project['name']
    version   = str(project.get('version', '0.0.0'))
    dist_info = f'{name}-{version}.dist-info'
    whl_path  = wheel_directory / f'{name}-{version}-py3-none-any.whl'

    metadata_bytes = _generate_pkg_info(
        name, version, _ProjectMetadata(project), project.get('dependencies'),
        project.get('optional-dependencies'), project, project_root,
    ).encode('utf-8')
    wheel_bytes = (
        'Wheel-Version: 1.0\n'
        'Generator: rbbuild\n'
        'Root-Is-Purelib: true\n'
        'Tag: py3-none-any\n'
    ).encode('utf-8')
    pth_bytes = (str(project_root) + '\n').encode('utf-8')

    record_rows = []

    with zipfile.ZipFile(whl_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in [
            (f'__editable__.{name}.pth', pth_bytes),
            (f'{dist_info}/WHEEL',       wheel_bytes),
            (f'{dist_info}/METADATA',    metadata_bytes),
        ]:
            zf.writestr(arcname, data)
            record_rows.append(f'{arcname},sha256={_sha256_digest(data)},{len(data)}')

        # An editable install is one distribution for all wheels of a
        # multi-wheel project, hence, it registers the entry points of all.
        packaging = pyproject_toml.get('tool', {}).get('rbbuild', {}).get('packaging', {})
        comp = {'entry_points': [
            ep
            for entry in packaging.values() if entry.get('type') == 'python'
            for ep in entry.get('entry-points', [])
        ]}
        ep_bytes = _build_entry_points_txt(pyproject_toml, comp)
        if ep_bytes:
            arcname = f'{dist_info}/entry_points.txt'
            zf.writestr(arcname, ep_bytes)
            record_rows.append(f'{arcname},sha256={_sha256_digest(ep_bytes)},{len(ep_bytes)}')

        # RECORD has no hash entry for itself (PEP 427)
        zf.writestr(f'{dist_info}/RECORD', '\n'.join(record_rows) + f'\n{dist_info}/RECORD,,\n')

    return whl_path.name


_README_CONTENT_TYPES = {
    '.md':  'text/markdown',
    '.rst': 'text/x-rst',
    '.txt': 'text/plain',
}


# Only UTF-8 is supported; it is the default when no charset is given.
def _check_readme_content_type(content_type):
    media_type, *params = [p.strip() for p in content_type.split(';')]
    if media_type.lower() not in _README_CONTENT_TYPES.values():
        raise ValueError(f'[project] readme: unsupported content-type "{content_type}"')
    for param in params:
        key, _, value = param.partition('=')
        if key.strip().lower() == 'charset' and value.strip().lower() != 'utf-8':
            raise ValueError(f'[project] readme: unsupported charset in "{content_type}"')


# Returns (content type, text) for [project].readme (PEP 621), or None if
# there is no readme or its file does not exist.
def _read_readme(readme, source_dir):
    if not readme:
        return None

    if isinstance(readme, str):
        suffix = Path(readme).suffix.lower()
        if suffix not in _README_CONTENT_TYPES:
            raise ValueError(
                f'[project] readme "{readme}": unrecognized suffix, '
                'use a table with content-type')
        readme = {'file': readme, 'content-type': _README_CONTENT_TYPES[suffix]}

    if ('file' in readme) == ('text' in readme):
        raise ValueError('[project] readme: specify exactly one of file and text')
    if 'content-type' not in readme:
        raise ValueError('[project] readme: content-type is required')

    content_type = readme['content-type']
    _check_readme_content_type(content_type)
    if 'text' in readme:
        return content_type, readme['text']

    path = Path(source_dir) / readme['file']
    if not path.is_file():
        return None
    return content_type, path.read_text(encoding='utf-8')


# Generates a PEP 566 / Core Metadata 2.1 PKG-INFO string from a Metadata object.
# requirements: optional list of PEP 508 dependency strings written as Requires-Dist headers.
# optional_requirements: optional {extra_name: [PEP 508 strings]} from
# [project.optional-dependencies], written as Provides-Extra/Requires-Dist
# with an `extra ==` marker (PEP 566/508).
# project: raw [project] table (PEP 621) for readme, keywords, classifiers,
# urls and requires-python; its keys must keep their hyphens and labels.
# source_dir: directory against which project.readme is resolved.
def _generate_pkg_info(
    name: str, version: str, metadata, requirements=None,
    optional_requirements=None, project=None, source_dir=None,
) -> str:
    project = project or {}
    lines = [
        'Metadata-Version: 2.1',
        f'Name: {name}',
        f'Version: {version}',
    ]

    description = metadata.config.get('description', '').strip()
    if description:
        lines.append(f'Summary: {description}')

    readme = _read_readme(project.get('readme'), source_dir)
    if readme:
        lines.append(f'Description-Content-Type: {readme[0]}')

    if project.get('keywords'):
        lines.append('Keywords: ' + ','.join(project['keywords']))

    for classifier in project.get('classifiers', []):
        lines.append(f'Classifier: {classifier}')

    for label, url in project.get('urls', {}).items():
        lines.append(f'Project-URL: {label}, {url}')

    if project.get('requires-python'):
        lines.append(f'Requires-Python: {project["requires-python"]}')

    for author in metadata.authors:
        aname  = author.get('name',  '').strip()
        aemail = author.get('email', '').strip()
        if aname and aemail:
            lines.append(f'Author-email: {aname} <{aemail}>')
        elif aemail:
            lines.append(f'Author-email: {aemail}')
        elif aname:
            lines.append(f'Author: {aname}')

    for maintainer in metadata.maintainers:
        mname  = maintainer.get('name',  '').strip()
        memail = maintainer.get('email', '').strip()
        if mname and memail:
            lines.append(f'Maintainer-email: {mname} <{memail}>')
        elif memail:
            lines.append(f'Maintainer-email: {memail}')
        elif mname:
            lines.append(f'Maintainer: {mname}')

    lic = metadata.license
    if lic:
        lic_text = lic.get('text') or lic.get('file', '') if isinstance(lic, dict) else str(lic)
        if lic_text:
            lines.append(f'License: {lic_text}')

    for req in (requirements or []):
        lines.append(f'Requires-Dist: {req}')

    for extra_name in (optional_requirements or {}):
        lines.append(f'Provides-Extra: {extra_name}')
    for extra_name, reqs in (optional_requirements or {}).items():
        for req in reqs:
            lines.append(f'Requires-Dist: {req}; extra == "{extra_name}"')

    pkg_info = '\n'.join(lines) + '\n'
    if readme:
        # The message body carries the long description.
        pkg_info += '\n' + readme[1]
    return pkg_info

