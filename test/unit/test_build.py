# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import tarfile
import zipfile

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from rbbuild.buildsystem.build import _generate_pkg_info, build_editable, build_sdist, build_wheel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Build a minimal Metadata mock.
def _make_metadata(name='mypkg', version='1.2.3.4', description='A package',
                   authors=None, maintainers=None, license_text='MIT'):
    m = MagicMock()
    m.name = name
    m.version = version
    m.config = {'description': description}
    m.authors = authors if authors is not None else [{'name': 'Alice', 'email': 'alice@example.com'}]
    m.maintainers = maintainers if maintainers is not None else []
    m.license = {'text': license_text}
    return m


# Build config_settings for build_sdist / build_wheel using real source files.
# scripts:     optional dict of {name: 'module:function'} for [project.scripts]
# gui_scripts: optional dict of {name: 'module:function'} for [project.gui-scripts]
# shared_data: optional list of (path, strip, dest) triplets for .data section
def _make_config_settings(tmp_path, files=None, shared_data=None, metadata=None, scripts=None, gui_scripts=None, optional_requirements=None):
    pypa = MagicMock()
    pypa.metadata = metadata if metadata is not None else _make_metadata()
    pypa.optional_requirements = optional_requirements or {}
    project = {}
    if scripts:
        project['scripts'] = scripts
    if gui_scripts:
        project['gui-scripts'] = gui_scripts
    pypa.pyproject_toml = {'project': project} if project else {}
    if files is not None:
        pypa.packaging.resolve_files.return_value = files
    pypa.packaging.resolve_excluded.return_value = set()
    pypa.packaging.resolve_shared_data.return_value = shared_data if shared_data is not None else []
    return {
        'rbbuild_python_backend': pypa,
        'package_name': 'wheel',
        'packaging_entry': {'type': 'python', 'files': ['mypkg']},
        'multi_wheel': False,
    }


# Chdir to tmp_path and create a minimal source package with relative paths.
# resolve_files always returns paths relative to cwd, so tests must do the same.
def _setup_build(tmp_path, monkeypatch, optional_requirements=None):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(src, None, '')], optional_requirements=optional_requirements)
    return sdist_dir, cs


# ---------------------------------------------------------------------------
# _generate_pkg_info — required fields
# ---------------------------------------------------------------------------

def test_pkg_info_has_metadata_version():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Metadata-Version: 2.1' in result


def test_pkg_info_has_name():
    m = _make_metadata(name='mylib')
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Name: mylib' in result


def test_pkg_info_has_version():
    m = _make_metadata(version='3.0.1.0')
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Version: 3.0.1.0' in result


# ---------------------------------------------------------------------------
# _generate_pkg_info — optional fields
# ---------------------------------------------------------------------------

def test_pkg_info_summary_from_description():
    m = _make_metadata(description='Great tool')
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Summary: Great tool' in result


def test_pkg_info_empty_description_omitted():
    m = _make_metadata(description='')
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Summary' not in result


def test_pkg_info_author_name_and_email():
    m = _make_metadata(authors=[{'name': 'Bob', 'email': 'bob@example.com'}])
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Author-email: Bob <bob@example.com>' in result


def test_pkg_info_author_email_only():
    m = _make_metadata(authors=[{'name': '', 'email': 'anon@example.com'}])
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Author-email: anon@example.com' in result


def test_pkg_info_author_name_only():
    m = _make_metadata(authors=[{'name': 'NoEmail', 'email': ''}])
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Author: NoEmail' in result


def test_pkg_info_maintainer_name_and_email():
    m = _make_metadata(maintainers=[{'name': 'Cara', 'email': 'c@example.com'}])
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Maintainer-email: Cara <c@example.com>' in result


def test_pkg_info_license_dict_text():
    m = _make_metadata(license_text='Apache-2.0')
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'License: Apache-2.0' in result


def test_pkg_info_license_none_omitted():
    m = _make_metadata()
    m.license = None
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'License' not in result


def test_pkg_info_ends_with_newline():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m)
    assert result.endswith('\n')


def test_pkg_info_requires_dist():
    m = _make_metadata()
    result = _generate_pkg_info(
        m.name, m.version, m,
        requirements=['requests>=2.0', 'packaging>=25.0'],
    )
    assert 'Requires-Dist: requests>=2.0' in result
    assert 'Requires-Dist: packaging>=25.0' in result


def test_pkg_info_no_requires_dist_when_empty():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m, requirements=[])
    assert 'Requires-Dist' not in result


def test_pkg_info_optional_requirements_provides_extra():
    m = _make_metadata()
    result = _generate_pkg_info(
        m.name, m.version, m,
        optional_requirements={'ui': ['PySide6>=6.11', 'pygments>=2.18']},
    )
    assert 'Provides-Extra: ui' in result
    assert 'Requires-Dist: PySide6>=6.11; extra == "ui"' in result
    assert 'Requires-Dist: pygments>=2.18; extra == "ui"' in result


def test_pkg_info_no_optional_requirements_no_provides_extra():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Provides-Extra' not in result


# ---------------------------------------------------------------------------
# _generate_pkg_info — [project] table fields
# ---------------------------------------------------------------------------

def test_pkg_info_readme_table_sets_content_type_and_body(tmp_path):
    (tmp_path / 'README.md').write_text('# Title\n\nBody\n', encoding='utf-8')
    m = _make_metadata()
    project = {'readme': {'file': 'README.md', 'content-type': 'text/markdown'}}
    result = _generate_pkg_info(
        m.name, m.version, m, project=project, source_dir=tmp_path)
    headers, body = result.split('\n\n', 1)
    assert 'Description-Content-Type: text/markdown' in headers
    assert body == '# Title\n\nBody\n'


def test_pkg_info_readme_string_infers_content_type(tmp_path):
    (tmp_path / 'README.rst').write_text('Title\n=====\n', encoding='utf-8')
    m = _make_metadata()
    result = _generate_pkg_info(
        m.name, m.version, m, project={'readme': 'README.rst'},
        source_dir=tmp_path)
    assert 'Description-Content-Type: text/x-rst' in result


def test_pkg_info_readme_text_table(tmp_path):
    m = _make_metadata()
    project = {'readme': {'text': 'Hello', 'content-type': 'text/plain'}}
    result = _generate_pkg_info(
        m.name, m.version, m, project=project, source_dir=tmp_path)
    assert result.endswith('\n\nHello')


def test_pkg_info_readme_suffix_is_case_insensitive(tmp_path):
    (tmp_path / 'README.MD').write_text('# T\n', encoding='utf-8')
    m = _make_metadata()
    result = _generate_pkg_info(
        m.name, m.version, m, project={'readme': 'README.MD'},
        source_dir=tmp_path)
    assert 'Description-Content-Type: text/markdown' in result


@pytest.mark.parametrize('readme', [
    'README',
    'README.adoc',
    {'file': 'README', 'content-type': 'text/html'},
    {'file': 'README.md', 'content-type': 'text/markdown; charset=latin-1'},
    {'file': 'README.md'},
    {'text': 'Hello'},
    {'file': 'README.md', 'text': 'Hello', 'content-type': 'text/plain'},
    {'content-type': 'text/plain'},
])
def test_pkg_info_invalid_readme_raises(tmp_path, readme):
    (tmp_path / 'README').write_text('x', encoding='utf-8')
    m = _make_metadata()
    with pytest.raises(ValueError, match='readme'):
        _generate_pkg_info(
            m.name, m.version, m, project={'readme': readme},
            source_dir=tmp_path)


def test_pkg_info_readme_content_type_parameters_accepted(tmp_path):
    (tmp_path / 'README.md').write_text('# T\n', encoding='utf-8')
    m = _make_metadata()
    project = {'readme': {
        'file': 'README.md', 'content-type': 'text/markdown; charset=UTF-8; variant=GFM'}}
    result = _generate_pkg_info(
        m.name, m.version, m, project=project, source_dir=tmp_path)
    assert 'Description-Content-Type: text/markdown; charset=UTF-8; variant=GFM' in result


def test_pkg_info_missing_readme_file_is_skipped(tmp_path):
    m = _make_metadata()
    result = _generate_pkg_info(
        m.name, m.version, m, project={'readme': 'README.md'},
        source_dir=tmp_path)
    assert 'Description-Content-Type' not in result
    assert result.endswith('\n') and not result.endswith('\n\n')


def test_pkg_info_no_readme_has_no_body():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m)
    assert 'Description-Content-Type' not in result
    assert '\n\n' not in result


def test_pkg_info_project_fields():
    m = _make_metadata()
    project = {
        'requires-python': '>= 3.14',
        'keywords': ['build', 'tool'],
        'classifiers': ['Topic :: Software Development', 'Intended Audience :: Developers'],
        'urls': {'Source Code': 'https://example.com/src', 'Bug-Tracker': 'https://example.com/bugs'},
    }
    result = _generate_pkg_info(m.name, m.version, m, project=project)
    assert 'Requires-Python: >= 3.14' in result
    assert 'Keywords: build,tool' in result
    assert 'Classifier: Topic :: Software Development' in result
    assert 'Classifier: Intended Audience :: Developers' in result
    assert 'Project-URL: Source Code, https://example.com/src' in result
    assert 'Project-URL: Bug-Tracker, https://example.com/bugs' in result


def test_pkg_info_project_fields_omitted_when_absent():
    m = _make_metadata()
    result = _generate_pkg_info(m.name, m.version, m, project={})
    for header in ('Requires-Python', 'Keywords', 'Classifier', 'Project-URL'):
        assert header not in result


def test_build_wheel_metadata_contains_readme(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    (tmp_path / 'README.md').write_text('# Hello\n', encoding='utf-8')
    pypa = cs['rbbuild_python_backend']
    pypa.paths.source = tmp_path
    pypa.pyproject_toml = {'project': {
        'readme': {'file': 'README.md', 'content-type': 'text/markdown'},
        'requires-python': '>= 3.14',
    }}
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        metadata = zf.read('mypkg-1.2.3.4.dist-info/METADATA').decode()
    assert 'Description-Content-Type: text/markdown' in metadata
    assert 'Requires-Python: >= 3.14' in metadata
    assert metadata.endswith('\n\n# Hello\n')


def test_build_sdist_pkg_info_contains_readme(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    (tmp_path / 'README.md').write_text('# Hello\n', encoding='utf-8')
    pypa = cs['rbbuild_python_backend']
    pypa.paths.source = tmp_path
    pypa.pyproject_toml = {'project': {'readme': 'README.md'}}
    pypa.requirements = []
    pypa.packaging.items.return_value = []
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name) as tar:
        pkg_info = tar.extractfile('mypkg-1.2.3.4/PKG-INFO').read().decode()
    assert 'Description-Content-Type: text/markdown' in pkg_info
    assert pkg_info.endswith('\n\n# Hello\n')


# ---------------------------------------------------------------------------
# build_sdist — raises without rbbuild backend
# ---------------------------------------------------------------------------

def test_build_sdist_raises_without_config(tmp_path):
    with pytest.raises(NotImplementedError):
        build_sdist(str(tmp_path), config_settings=None)


def test_build_sdist_raises_without_rbbuild_key(tmp_path):
    with pytest.raises(NotImplementedError):
        build_sdist(str(tmp_path), config_settings={'package_name': 'x'})


# ---------------------------------------------------------------------------
# build_sdist — output
# ---------------------------------------------------------------------------

def test_build_sdist_returns_filename(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    assert name == 'mypkg-1.2.3.4.tar.gz'


def test_build_sdist_file_exists(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    assert (sdist_dir / name).exists()


def test_build_sdist_contains_pkg_info(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        assert 'mypkg-1.2.3.4/PKG-INFO' in tar.getnames()


def test_build_sdist_all_entries_under_prefix(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    assert all(n.startswith('mypkg-1.2.3.4/') for n in names)


def test_build_sdist_source_file_present(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    assert any('__init__.py' in n for n in names)


def test_build_sdist_stores_at_source_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(src, None, 'lib')])
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    # dest is a wheel-placement concern only; sdist must store at the original source path
    assert 'mypkg-1.2.3.4/mypkg/__init__.py' in names
    assert not any('lib' in n for n in names)


# ---------------------------------------------------------------------------
# build_wheel — raises without rbbuild backend
# ---------------------------------------------------------------------------

def test_build_wheel_raises_without_config(tmp_path):
    with pytest.raises(NotImplementedError):
        build_wheel(str(tmp_path), config_settings=None)


def test_build_wheel_raises_without_rbbuild_key(tmp_path):
    with pytest.raises(NotImplementedError):
        build_wheel(str(tmp_path), config_settings={'package_name': 'x'})


# ---------------------------------------------------------------------------
# build_wheel — output
# ---------------------------------------------------------------------------

def test_build_wheel_returns_filename(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    assert name == 'mypkg-1.2.3.4-py3-none-any.whl'


def test_build_wheel_file_exists(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    assert (sdist_dir / name).exists()


def test_build_wheel_contains_wheel_file(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        assert 'mypkg-1.2.3.4.dist-info/WHEEL' in zf.namelist()


def test_build_wheel_contains_metadata(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        assert 'mypkg-1.2.3.4.dist-info/METADATA' in zf.namelist()


def test_build_wheel_metadata_contains_optional_dependencies(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(
        tmp_path, monkeypatch, optional_requirements={'ui': ['PySide6>=6.11']})
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        metadata = zf.read('mypkg-1.2.3.4.dist-info/METADATA').decode()
    assert 'Provides-Extra: ui' in metadata
    assert 'Requires-Dist: PySide6>=6.11; extra == "ui"' in metadata


def test_build_wheel_contains_record(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        assert 'mypkg-1.2.3.4.dist-info/RECORD' in zf.namelist()


def test_build_wheel_metadata_has_name_and_version(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        metadata = zf.read('mypkg-1.2.3.4.dist-info/METADATA').decode()
    assert 'Name: mypkg' in metadata
    assert 'Version: 1.2.3.4' in metadata


def test_build_wheel_wheel_file_tag(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        wheel_txt = zf.read('mypkg-1.2.3.4.dist-info/WHEEL').decode()
    assert 'Tag: py3-none-any' in wheel_txt
    assert 'Root-Is-Purelib: true' in wheel_txt


def test_build_wheel_record_self_entry_has_no_hash(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        record = zf.read('mypkg-1.2.3.4.dist-info/RECORD').decode()
    record_self = next(line for line in record.splitlines() if 'RECORD' in line)
    assert record_self.endswith(',,')


def test_build_wheel_source_files_at_top_level(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        names = zf.namelist()
    # Source files must not be nested under a {name}-{version}/ prefix
    source_entries = [n for n in names if not n.startswith('mypkg-1.2.3.4.dist-info/')]
    assert source_entries, 'No source files found in wheel'
    assert all(not n.startswith('mypkg-1.2.3.4/') for n in source_entries)


# ---------------------------------------------------------------------------
# build_wheel — entry_points.txt
# ---------------------------------------------------------------------------

def test_build_wheel_no_entry_points_txt_when_no_scripts(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        assert 'mypkg-1.2.3.4.dist-info/entry_points.txt' not in zf.namelist()


def test_build_wheel_contains_entry_points_txt_when_scripts_defined(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(src, None, '')],
        scripts={'mycli': 'mypkg:run'},
    )
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        assert 'mypkg-1.2.3.4.dist-info/entry_points.txt' in zf.namelist()


def test_build_wheel_entry_points_txt_console_scripts_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(src, None, '')],
        scripts={'mycli': 'mypkg:run', 'myother': 'mypkg.sub:main'},
    )
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        ep = zf.read('mypkg-1.2.3.4.dist-info/entry_points.txt').decode()
    assert '[console_scripts]' in ep
    assert 'mycli = mypkg:run' in ep
    assert 'myother = mypkg.sub:main' in ep


def test_build_wheel_entry_points_txt_in_record(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(src, None, '')],
        scripts={'mycli': 'mypkg:run'},
    )
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        record = zf.read('mypkg-1.2.3.4.dist-info/RECORD').decode()
    assert 'entry_points.txt' in record


def test_build_wheel_gui_scripts_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(src, None, '')],
        gui_scripts={'mygui': 'mypkg.gui:main'},
    )
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        ep = zf.read('mypkg-1.2.3.4.dist-info/entry_points.txt').decode()
    assert '[gui_scripts]' in ep
    assert 'mygui = mypkg.gui:main' in ep
    assert '[console_scripts]' not in ep


def test_build_wheel_both_scripts_and_gui_scripts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(src, None, '')],
        scripts={'mycli': 'mypkg:run'},
        gui_scripts={'mygui': 'mypkg.gui:main'},
    )
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        ep = zf.read('mypkg-1.2.3.4.dist-info/entry_points.txt').decode()
    assert '[console_scripts]' in ep
    assert 'mycli = mypkg:run' in ep
    assert '[gui_scripts]' in ep
    assert 'mygui = mypkg.gui:main' in ep


# Builds a wheel for the given packaging entry settings and returns
# (METADATA text, entry_points.txt text or None).
def _build_wheel_metadata(tmp_path, monkeypatch, project=None, comp_extra=None,
                          requirements=None, siblings=None):
    monkeypatch.chdir(tmp_path)
    pkg = Path('mypkg')
    pkg.mkdir(exist_ok=True)
    src = pkg / '__init__.py'
    src.write_text('# mypkg')
    whl_dir = tmp_path / 'out'
    whl_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(src, None, '')])
    pypa = cs['rbbuild_python_backend']
    pypa.pyproject_toml = {'project': project or {}}
    pypa.requirements = requirements or []
    pypa.packaging.items.return_value = siblings or []
    cs['packaging_entry'] = {**cs['packaging_entry'], **(comp_extra or {})}
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        metadata = zf.read('mypkg-1.2.3.4.dist-info/METADATA').decode()
        ep_name = 'mypkg-1.2.3.4.dist-info/entry_points.txt'
        ep = zf.read(ep_name).decode() if ep_name in zf.namelist() else None
    return metadata, ep


def test_build_wheel_project_entry_points_group(tmp_path, monkeypatch):
    _, ep = _build_wheel_metadata(
        tmp_path, monkeypatch,
        project={'entry-points': {'rbbuild.repository': {'csi': 'mypkg.csi:CSI'}}},
    )
    assert '[rbbuild.repository]' in ep
    assert 'csi = mypkg.csi:CSI' in ep


def test_build_wheel_packaging_entry_entry_points(tmp_path, monkeypatch):
    _, ep = _build_wheel_metadata(
        tmp_path, monkeypatch,
        comp_extra={'entry_points': [
            {'group': 'rbbuild.repository', 'name': 'csi', 'value': 'mypkg.csi:CSI'},
        ]},
    )
    assert '[rbbuild.repository]' in ep
    assert 'csi = mypkg.csi:CSI' in ep


def test_build_wheel_packaging_entry_entry_points_missing_key_raises(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='entry-points'):
        _build_wheel_metadata(
            tmp_path, monkeypatch,
            comp_extra={'entry_points': [{'group': 'rbbuild.repository', 'name': 'csi'}]},
        )


def test_build_wheel_entry_points_merge_project_and_entry(tmp_path, monkeypatch):
    _, ep = _build_wheel_metadata(
        tmp_path, monkeypatch,
        project={
            'scripts': {'mycli': 'mypkg:run'},
            'entry-points': {'grp': {'a': 'mypkg:a'}},
        },
        comp_extra={'entry_points': [{'group': 'grp', 'name': 'b', 'value': 'mypkg:b'}]},
    )
    assert '[console_scripts]' in ep
    assert ep.count('[grp]') == 1
    assert 'a = mypkg:a' in ep
    assert 'b = mypkg:b' in ep


def test_build_wheel_depends_on_exact_pin(tmp_path, monkeypatch):
    metadata, _ = _build_wheel_metadata(
        tmp_path, monkeypatch,
        comp_extra={'depends_on': ['extra']},
        requirements=['rbbuild>=6.0'],
        siblings=[('wheel', {'type': 'python'}), ('extra', {'type': 'python'})],
    )
    assert 'Requires-Dist: rbbuild>=6.0' in metadata
    assert 'Requires-Dist: mypkg_extra==1.2.3.4' in metadata


def test_build_wheel_depends_on_single_string(tmp_path, monkeypatch):
    metadata, _ = _build_wheel_metadata(
        tmp_path, monkeypatch,
        comp_extra={'depends_on': 'extra'},
        siblings=[('wheel', {'type': 'python'}), ('extra', {'type': 'python'})],
    )
    assert 'Requires-Dist: mypkg_extra==1.2.3.4' in metadata


def test_build_wheel_depends_on_name_normalized(tmp_path, monkeypatch):
    metadata, _ = _build_wheel_metadata(
        tmp_path, monkeypatch,
        comp_extra={'depends_on': ['my-extra']},
        siblings=[('wheel', {'type': 'python'}), ('my_extra', {'type': 'python'})],
    )
    assert 'Requires-Dist: mypkg_my_extra==1.2.3.4' in metadata


def test_build_wheel_depends_on_absent_no_pin(tmp_path, monkeypatch):
    metadata, _ = _build_wheel_metadata(
        tmp_path, monkeypatch,
        requirements=['rbbuild>=6.0'],
        siblings=[('wheel', {'type': 'python'}), ('extra', {'type': 'python'})],
    )
    assert 'mypkg_extra' not in metadata


def test_build_wheel_depends_on_unknown_entry_raises(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='depends-on'):
        _build_wheel_metadata(
            tmp_path, monkeypatch,
            comp_extra={'depends_on': ['nope']},
            siblings=[('wheel', {'type': 'python'})],
        )


def test_build_wheel_depends_on_non_python_entry_raises(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='depends-on'):
        _build_wheel_metadata(
            tmp_path, monkeypatch,
            comp_extra={'depends_on': ['plain']},
            siblings=[('plain', {'files': ['x']})],
        )


def test_build_wheel_depends_on_self_raises(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='must not refer to itself'):
        _build_wheel_metadata(
            tmp_path, monkeypatch,
            comp_extra={'depends_on': ['wheel']},
            siblings=[('wheel', {'type': 'python'})],
        )


def test_build_sdist_depends_on_exact_pin(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    pypa = cs['rbbuild_python_backend']
    pypa.requirements = []
    pypa.packaging.items.return_value = [('wheel', {'type': 'python'}), ('extra', {'type': 'python'})]
    cs['packaging_entry'] = {**cs['packaging_entry'], 'depends_on': ['extra']}
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name) as tar:
        pkg_info = tar.extractfile('mypkg-1.2.3.4/PKG-INFO').read().decode()
    assert 'Requires-Dist: mypkg_extra==1.2.3.4' in pkg_info


# ---------------------------------------------------------------------------
# build_wheel - platform-specific wheels
# ---------------------------------------------------------------------------

# Toolchain data as resolved from the profile (toolchains/<tcid>.toml).
def _toolchain(wheel_platform_tag=None):
    return SimpleNamespace(wheel_platform_tag=wheel_platform_tag)


_HOST_TOOLCHAIN = _toolchain('linux_x86_64')


# Builds a wheel for a platform-specific packaging entry; returns
# (wheel filename, WHEEL file content).
def _build_platform_wheel(tmp_path, monkeypatch, toolchain=_HOST_TOOLCHAIN, **entry):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    cs['packaging_entry'] = {**cs['packaging_entry'], **entry}
    cs['toolchain'] = toolchain
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        return name, zf.read('mypkg-1.2.3.4.dist-info/WHEEL').decode()


def test_build_wheel_platform_specific_tag(tmp_path, monkeypatch):
    name, wheel_txt = _build_platform_wheel(
        tmp_path, monkeypatch, platform_specific=True)
    assert name == 'mypkg-1.2.3.4-py3-none-linux_x86_64.whl'
    assert 'Tag: py3-none-linux_x86_64' in wheel_txt
    assert 'Root-Is-Purelib: false' in wheel_txt


# Builds a wheel that contains the given files (platform-specific entry).
def _build_wheel_with_files(tmp_path, monkeypatch, filenames, toolchain=_HOST_TOOLCHAIN):
    monkeypatch.chdir(tmp_path)
    Path('ext').mkdir()
    files = []
    for filename in filenames:
        path = Path('ext') / filename
        path.write_bytes(b'x')
        files.append((path, 'ext', 'mypkg'))
    whl_dir = tmp_path / 'out'
    whl_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=files)
    cs['packaging_entry'] = {'type': 'python', 'platform_specific': True}
    cs['toolchain'] = toolchain
    return build_wheel(wheel_directory=whl_dir, config_settings=cs)


# The Python version of extension modules selects the cpXY tag.
@pytest.mark.parametrize('filename', [
    '_x.cpython-312-x86_64-linux-gnu.so',
    '_x.cp312-win_amd64.pyd',
])
def test_build_wheel_cpython_tag_from_extension_module(tmp_path, monkeypatch, filename):
    name = _build_wheel_with_files(tmp_path, monkeypatch, ['__init__.py', filename])
    assert name == 'mypkg-1.2.3.4-cp312-cp312-linux_x86_64.whl'


@pytest.mark.parametrize('filename', [
    '_x.pypy310-pp73-x86_64-linux-gnu.so',
    '_x.pypy310-pp73-win_amd64.pyd',
])
def test_build_wheel_pypy_tag_from_extension_module(tmp_path, monkeypatch, filename):
    name = _build_wheel_with_files(tmp_path, monkeypatch, ['__init__.py', filename])
    assert name == 'mypkg-1.2.3.4-pp310-pypy310_pp73-linux_x86_64.whl'


def test_build_wheel_cpython_and_pypy_modules_raise(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='several Python versions'):
        _build_wheel_with_files(
            tmp_path, monkeypatch, ['_x.cp312-win_amd64.pyd', '_y.pypy310-pp73-win_amd64.pyd'])


def test_build_wheel_cpython_tag_with_toolchain_tag(tmp_path, monkeypatch):
    name = _build_wheel_with_files(
        tmp_path, monkeypatch, ['_x.cp313-win32.pyd'], toolchain=_toolchain('win32'))
    assert name == 'mypkg-1.2.3.4-cp313-cp313-win32.whl'


# A plain shared library (e.g., for ctypes) does not depend on the Python ABI.
def test_build_wheel_no_extension_module_is_py3_none(tmp_path, monkeypatch):
    name = _build_wheel_with_files(tmp_path, monkeypatch, ['libgreet.so'])
    assert name == 'mypkg-1.2.3.4-py3-none-linux_x86_64.whl'


def test_build_wheel_abi3_extension_raises(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='abi3'):
        _build_wheel_with_files(tmp_path, monkeypatch, ['_x.abi3.so'])


def test_build_wheel_extension_modules_of_several_versions_raise(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='several Python versions'):
        _build_wheel_with_files(
            tmp_path, monkeypatch, ['_x.cp312-win_amd64.pyd', '_y.cp313-win_amd64.pyd'])


# A non-default toolchain brings its own platform tag.
def test_build_wheel_platform_tag_from_toolchain(tmp_path, monkeypatch):
    name, wheel_txt = _build_platform_wheel(
        tmp_path, monkeypatch, toolchain=_toolchain('linux_armv7l'),
        platform_specific=True)
    assert name == 'mypkg-1.2.3.4-py3-none-linux_armv7l.whl'
    assert 'Tag: py3-none-linux_armv7l' in wheel_txt


# An explicit tag is used as-is; no toolchain is needed.
def test_build_wheel_explicit_wheel_tag(tmp_path, monkeypatch):
    name, wheel_txt = _build_platform_wheel(
        tmp_path, monkeypatch, toolchain=None, platform_specific=True,
        wheel_tag='py3-none-linux_armv7l')
    assert name == 'mypkg-1.2.3.4-py3-none-linux_armv7l.whl'
    assert 'Tag: py3-none-linux_armv7l' in wheel_txt
    assert 'Root-Is-Purelib: false' in wheel_txt


@pytest.mark.parametrize('toolchain', [
    None,
    _toolchain(),
])
def test_build_wheel_platform_tag_not_derivable_raises(tmp_path, monkeypatch, toolchain):
    with pytest.raises(SyntaxError, match='wheel-tag'):
        _build_platform_wheel(
            tmp_path, monkeypatch, toolchain=toolchain, platform_specific=True)


def test_build_wheel_wheel_tag_requires_platform_specific(tmp_path, monkeypatch):
    with pytest.raises(SyntaxError, match='platform-specific'):
        _build_platform_wheel(
            tmp_path, monkeypatch, wheel_tag='py3-none-linux_x86_64')


# A compiled library is placed next to the Python sources of its package.
def test_build_wheel_platform_specific_contains_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'obj/tc').mkdir(parents=True)
    lib = Path('obj/tc/libgreet.so')
    lib.write_bytes(b'\x7fELF')
    whl_dir = tmp_path / 'out'
    whl_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(lib, 'obj/tc', 'mypkg')])
    cs['packaging_entry'] = {'type': 'python', 'platform_specific': True}
    cs['toolchain'] = _HOST_TOOLCHAIN
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        assert 'mypkg/libgreet.so' in zf.namelist()


# files = ['python_example']  →  resolve_files returns the directory itself.
# build_wheel must expand it recursively into individual file entries.
def test_build_wheel_expands_directory_recursively(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('python_example')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('# pkg')
    (pkg_dir / 'module.py').write_text('# mod')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(pkg_dir, None, '')])
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    assert 'python_example/__init__.py' in names
    assert 'python_example/module.py' in names
    # The bare directory entry must not appear as a zip member
    assert 'python_example' not in names


# files = ['python_example/*.py']  →  resolve_files returns individual file paths.
# build_wheel must include every matched file in the wheel at the correct path.
def test_build_wheel_glob_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('python_example')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    (pkg_dir / 'module.py').write_text('')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    # Simulate glob result: individual files as returned by resolve_files
    cs = _make_config_settings(tmp_path, files=[
        (pkg_dir / '__init__.py', None, ''),
        (pkg_dir / 'module.py',   None, ''),
    ])
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    assert 'python_example/__init__.py' in names
    assert 'python_example/module.py' in names


# files = ['python_example']  →  resolve_files returns the directory itself.
# build_sdist wraps tar.add which recurses automatically; verify all files land
# under the archive prefix.
def test_build_sdist_directory_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('python_example')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('# pkg')
    (pkg_dir / 'module.py').write_text('# mod')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(pkg_dir, None, '')])
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    assert all(n.startswith('mypkg-1.2.3.4/') for n in names)
    assert any('__init__.py' in n for n in names)
    assert any('module.py' in n for n in names)


# files = ['python_example/*.py']  →  resolve_files returns individual file paths.
# Verify each matched file appears in the sdist under the archive prefix.
def test_build_sdist_glob_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('python_example')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    (pkg_dir / 'module.py').write_text('')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[
        (pkg_dir / '__init__.py', None, ''),
        (pkg_dir / 'module.py',   None, ''),
    ])
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    assert 'mypkg-1.2.3.4/python_example/__init__.py' in names
    assert 'mypkg-1.2.3.4/python_example/module.py' in names


# __pycache__ inside a directory entry must not appear in the wheel.
def test_build_wheel_excludes_pycache_from_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('mypkg')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    pycache = pkg_dir / '__pycache__'
    pycache.mkdir()
    (pycache / '__init__.cpython-311.pyc').write_bytes(b'')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(pkg_dir, None, '')])
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    assert 'mypkg/__init__.py' in names
    assert not any('__pycache__' in n for n in names)


# __pycache__ inside a directory entry must not appear in the sdist.
def test_build_sdist_excludes_pycache_from_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('mypkg')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    pycache = pkg_dir / '__pycache__'
    pycache.mkdir()
    (pycache / '__init__.cpython-311.pyc').write_bytes(b'')
    sdist_dir = tmp_path / 'mypkg-1.2.3.4'
    sdist_dir.mkdir()
    cs = _make_config_settings(tmp_path, files=[(pkg_dir, None, '')])
    name = build_sdist(sdist_directory=sdist_dir, config_settings=cs)
    with tarfile.open(sdist_dir / name, 'r:gz') as tar:
        names = tar.getnames()
    assert 'mypkg-1.2.3.4/mypkg/__init__.py' in names
    assert not any('__pycache__' in n for n in names)


# ---------------------------------------------------------------------------
# build_wheel — exclude during rglob expansion
# ---------------------------------------------------------------------------

# Files in a subdirectory that is listed in resolve_excluded must be omitted
# even when the parent directory is passed as a directory entry from resolve_files.
def test_build_wheel_excluded_subdir_omitted_from_wheel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('mypkg')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    data_dir = pkg_dir / 'data'
    data_dir.mkdir()
    (data_dir / 'config.cfg').write_text('[s]')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    excluded = {data_dir / 'config.cfg', data_dir}
    cs = _make_config_settings(tmp_path, files=[(pkg_dir, None, '')])
    cs['rbbuild_python_backend'].packaging.resolve_excluded.return_value = excluded
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    assert 'mypkg/__init__.py' in names
    assert not any('config.cfg' in n for n in names)


# ---------------------------------------------------------------------------
# build_wheel — .data section from shared_data
# ---------------------------------------------------------------------------

def _setup_shared_data_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('mypkg')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('# mypkg')
    data_file = Path('config.cfg')
    data_file.write_text('[defaults]\nkey=value\n')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(pkg_dir, None, '')],
        shared_data=[(data_file, None, 'share/mypkg')],
    )
    return whl_dir, cs


def test_build_wheel_shared_data_entry_in_data_section(tmp_path, monkeypatch):
    whl_dir, cs = _setup_shared_data_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    assert any('.data/data/share/mypkg' in n and 'config.cfg' in n for n in names)


def test_build_wheel_shared_data_not_in_purelib_root(tmp_path, monkeypatch):
    whl_dir, cs = _setup_shared_data_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    # The data file must not appear at the purelib root
    assert 'config.cfg' not in names


def test_build_wheel_shared_data_in_record(tmp_path, monkeypatch):
    whl_dir, cs = _setup_shared_data_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        record = zf.read('mypkg-1.2.3.4.dist-info/RECORD').decode()
    assert '.data/data/share/mypkg' in record
    assert 'config.cfg' in record


def test_build_wheel_shared_data_strip_applied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg_dir = Path('mypkg')
    pkg_dir.mkdir()
    (pkg_dir / '__init__.py').write_text('')
    data_dir = tmp_path / 'pkg_data'
    data_dir.mkdir()
    (data_dir / 'defaults.cfg').write_text('')
    whl_dir = tmp_path / 'mypkg-1.2.3.4'
    whl_dir.mkdir()
    cs = _make_config_settings(
        tmp_path,
        files=[(pkg_dir, None, '')],
        shared_data=[(data_dir / 'defaults.cfg', str(data_dir), 'share/mypkg')],
    )
    name = build_wheel(wheel_directory=whl_dir, config_settings=cs)
    with zipfile.ZipFile(whl_dir / name) as zf:
        names = zf.namelist()
    # strip applied: 'pkg_data' prefix removed, file stored as share/mypkg/defaults.cfg
    assert any(n.endswith('share/mypkg/defaults.cfg') for n in names)


def test_build_wheel_no_shared_data_no_data_section(tmp_path, monkeypatch):
    sdist_dir, cs = _setup_build(tmp_path, monkeypatch)
    name = build_wheel(wheel_directory=sdist_dir, config_settings=cs)
    with zipfile.ZipFile(sdist_dir / name) as zf:
        names = zf.namelist()
    assert not any('.data/' in n for n in names)


# ---------------------------------------------------------------------------
# build_editable() — PEP 660 editable installs (uv/pip install -e .)
# ---------------------------------------------------------------------------

# Writes a minimal pyproject.toml to tmp_path and chdir's there, mirroring
# what a PEP 517 frontend does before invoking a build hook.
def _write_pyproject(tmp_path, monkeypatch, extra_project=None):
    monkeypatch.chdir(tmp_path)
    project = {
        'name': 'mypkg',
        'version': '1.2.3',
        'description': 'A package',
        'authors': [{'name': 'Alice', 'email': 'alice@example.com'}],
    }
    if extra_project:
        project.update(extra_project)

    lines = ['[project]']
    for key, value in project.items():
        if isinstance(value, str):
            lines.append(f'{key} = {value!r}')
    lines.append('')

    # scripts / gui-scripts / dependencies need their own TOML tables/arrays
    if 'scripts' in project:
        lines.append('[project.scripts]')
        for name, ref in project['scripts'].items():
            lines.append(f'{name} = {ref!r}')
        lines.append('')
    if 'gui-scripts' in project:
        lines.append('[project.gui-scripts]')
        for name, ref in project['gui-scripts'].items():
            lines.append(f'{name} = {ref!r}')
        lines.append('')

    (tmp_path / 'pyproject.toml').write_text('\n'.join(lines))
    return tmp_path


def test_build_editable_returns_filename(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    assert name == 'mypkg-1.2.3-py3-none-any.whl'


def test_build_editable_file_exists(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    assert (tmp_path / name).exists()


def test_build_editable_pth_points_at_project_root(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        pth_names = [n for n in zf.namelist() if n.endswith('.pth')]
        assert len(pth_names) == 1
        content = zf.read(pth_names[0]).decode()
    assert content.strip() == str(tmp_path)


def test_build_editable_contains_metadata_with_name_and_version(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        metadata = zf.read('mypkg-1.2.3.dist-info/METADATA').decode()
    assert 'Name: mypkg' in metadata
    assert 'Version: 1.2.3' in metadata


def test_build_editable_no_entry_points_txt_when_no_scripts(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        names = zf.namelist()
    assert not any(n.endswith('entry_points.txt') for n in names)


def test_build_editable_contains_entry_points_txt_when_scripts_defined(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch, extra_project={'scripts': {'mycli': 'mypkg:main'}})
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        entry_points = zf.read('mypkg-1.2.3.dist-info/entry_points.txt').decode()
    assert '[console_scripts]' in entry_points
    assert 'mycli = mypkg:main' in entry_points


_MULTI_WHEEL_PYPROJECT = '''\
[project]
name = 'mypkg'
version = '1.2.3'

[tool.rbbuild.packaging.alpha]
type = 'python'
files = ['mypkg_alpha']
entry-points = [
    {group = 'rbbuild.config', name = 'alpha', value = 'mypkg_alpha'},
]

[tool.rbbuild.packaging.beta]
type = 'python'
files = ['mypkg_beta']
entry-points = [
    {group = 'rbbuild.config', name = 'beta', value = 'mypkg_beta'},
    {group = 'rbbuild.repository', name = 'repo', value = 'mypkg_beta.repo:Repo'},
]

[tool.rbbuild.packaging.docs]
type = 'plain'
files = ['README.md']
entry-points = [
    {group = 'ignored', name = 'x', value = 'y'},
]
'''


def test_build_editable_registers_entry_points_of_all_python_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(_MULTI_WHEEL_PYPROJECT)
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        entry_points = zf.read('mypkg-1.2.3.dist-info/entry_points.txt').decode()
    assert entry_points.count('[rbbuild.config]') == 1
    assert 'alpha = mypkg_alpha' in entry_points
    assert 'beta = mypkg_beta' in entry_points
    assert 'repo = mypkg_beta.repo:Repo' in entry_points
    assert 'ignored' not in entry_points


def test_build_editable_contains_record(tmp_path, monkeypatch):
    _write_pyproject(tmp_path, monkeypatch)
    name = build_editable(wheel_directory=tmp_path)
    with zipfile.ZipFile(tmp_path / name) as zf:
        names = zf.namelist()
    assert 'mypkg-1.2.3.dist-info/RECORD' in names

