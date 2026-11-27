#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import json
import pytest

from pathlib import Path
from unittest.mock import MagicMock, patch

from rbbuild.core.channel import Channel
from rbbuild.core.runtime_settings import OperationMode
from rbbuild.package.package import Package
from rbbuild.package.component import Component
from rbbuild.promote import PromoteMain, parse_command_line
from rbbuild.resolver.resolver import ResolveResult
from rbbuild.service.repository.manager import RepositoryManager


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _op_mode(**kwargs) -> OperationMode:
    defaults = dict(
        debug=False, verbose=False, force=False, ignore_errors=False,
        dry_run=False, offline=False, manifest_only=False, transitive=True,
    )
    defaults.update(kwargs)
    return OperationMode(**defaults)


def _channel(name: str) -> Channel:
    ch = MagicMock(spec=Channel)
    ch.name = name
    ch.repository = 'libs-local'
    ch.root_path = 'components'
    return ch


def _pkg(name: str, version: str, channel_name: str) -> Package:
    ch = _channel(channel_name)
    comp = Component(name=name, suffix='dev', build_only=False)
    p = Package(name=name, version=version)
    p.channel = ch
    p.components = [comp]
    return p


def _deps_parser(pkg: Package):
    dp = MagicMock()
    dp.parse_item.return_value = pkg
    return dp


def _resolver(resolved: dict):
    r = MagicMock()
    r.run.return_value = ResolveResult(packages=resolved, problems=[])
    return r


# ---------------------------------------------------------------------------
# parse_command_line
# ---------------------------------------------------------------------------

def test_parse_channel_map():
    args = parse_command_line(['-m', 'dev:test', 'mypkg-1.0'])
    assert args.channel_map == 'dev:test'
    assert args.package == 'mypkg-1.0'


def test_parse_dry_run():
    args = parse_command_line(['-n', '-m', 'dev:test'])
    assert args.dry_run is True


def test_parse_no_traverse():
    args = parse_command_line(['--no-traverse', '-m', 'dev:test'])
    assert args.no_traverse is True


def test_parse_tag():
    args = parse_command_line(['-T', '-m', 'dev:test', 'pkg-1.0'])
    assert args.tag is True


def test_parse_map_file():
    args = parse_command_line(['-M', 'map.json', 'pkg-1.0'])
    assert args.map_file == 'map.json'


def test_parse_all_packages():
    args = parse_command_line(['-A', '-m', 'dev:test'])
    assert args.all_packages is True


# ---------------------------------------------------------------------------
# do_promote — channel_map lookup uses channel name (str key)
# ---------------------------------------------------------------------------

# destination_channel must be looked up by channel name string, not Channel object.
def test_do_promote_channel_name_key():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')
    target_ch = _channel('test')

    # key by name (str) — this is the correct post-fix behaviour
    channel_map = {'dev': target_ch}
    resolver = _resolver({repr(pkg): pkg})
    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    repoman.promote.return_value = iter([])
    op_mode = _op_mode()

    with patch('rbbuild.promote.term'):
        promote.do_promote(
            ['dev:mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    resolver.run.assert_called_once_with({repr(pkg): pkg}, transitive=True)
    repoman.promote.assert_called_once_with(pkg=pkg, destination_channel=target_ch)


# A package whose channel has no mapping is skipped, not an error.
def test_do_promote_skips_unmapped_channel():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'other-channel')
    channel_map = {'dev': _channel('test')}  # 'other-channel' is not mapped
    resolver = _resolver({repr(pkg): pkg})
    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    op_mode = _op_mode()

    with patch('rbbuild.promote.term'):
        # Should not raise
        promote.do_promote(
            ['dev:mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    repoman.promote.assert_not_called()


# When dry_run=True, resolver.run() must never be called (no network calls).
def test_do_promote_dry_run_no_network_call():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')
    target_ch = _channel('test')
    channel_map = {'dev': target_ch}
    resolver = _resolver({})
    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    op_mode = _op_mode(dry_run=True)

    with patch('rbbuild.promote.term'):
        promote.do_promote(
            ['dev:mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    resolver.run.assert_not_called()
    repoman.promote.assert_not_called()


# When dry_run=True and the package has an explicit channel, the message includes '(dry run)'.
def test_do_promote_dry_run_message_with_channel():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')
    target_ch = _channel('test')
    channel_map = {'dev': target_ch}
    resolver = _resolver({})
    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    op_mode = _op_mode(dry_run=True)

    captured_messages = []
    with patch('rbbuild.promote.term') as mock_term:
        mock_term.magenta.side_effect = lambda x: x
        mock_term.bright_white.side_effect = lambda x: x
        mock_term.cyan.side_effect = lambda x: x
        mock_term.info.side_effect = lambda msg, **kw: captured_messages.append(str(msg))
        mock_term.warning.side_effect = lambda *a, **kw: None

        promote.do_promote(
            ['dev:mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    assert any('dry run' in m for m in captured_messages)
    assert any('dev' in m and 'test' in m for m in captured_messages)


# When dry_run=True and the package has no channel prefix, all channel mappings are shown.
def test_do_promote_dry_run_no_channel_prefix_shows_all_mappings():
    promote = PromoteMain()
    # Pkg without channel (parse_item result when no channel prefix in string)
    pkg = Package(name='mypkg', version='1.0')
    pkg.channel = None

    channel_map = {'dev': _channel('test'), 'staging': _channel('prod')}
    resolver = _resolver({})
    deps_parser = MagicMock()
    deps_parser.parse_item.return_value = pkg
    repoman = MagicMock()
    op_mode = _op_mode(dry_run=True)

    captured_messages = []
    with patch('rbbuild.promote.term') as mock_term:
        mock_term.magenta.side_effect = lambda x: x
        mock_term.bright_white.side_effect = lambda x: x
        mock_term.cyan.side_effect = lambda x: x
        mock_term.info.side_effect = lambda msg, **kw: captured_messages.append(str(msg))
        mock_term.warning.side_effect = lambda *a, **kw: None

        promote.do_promote(
            ['mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    resolver.run.assert_not_called()
    # One message per channel mapping
    dry_run_msgs = [m for m in captured_messages if 'dry run' in m]
    assert len(dry_run_msgs) == 2


# transitive=False (from --no-traverse) is forwarded to resolver.run().
def test_do_promote_transitive_false_passes_through():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')
    channel_map = {'dev': _channel('test')}
    resolver = _resolver({repr(pkg): pkg})
    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    repoman.promote.return_value = iter([])
    op_mode = _op_mode(transitive=False)

    with patch('rbbuild.promote.term'):
        promote.do_promote(
            ['dev:mypkg-1.0'], channel_map, 0, 1,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    _, call_kwargs = resolver.run.call_args
    assert call_kwargs['transitive'] is False


# With ignore_errors=True a SyntaxError in one item does not stop the loop.
def test_do_promote_ignore_errors_continues(capsys):
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')

    call_count = 0

    def raising_parse(item):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise SyntaxError('bad manifest')
        return pkg

    deps_parser = MagicMock()
    deps_parser.parse_item.side_effect = raising_parse

    resolver = _resolver({repr(pkg): pkg})
    op_mode = _op_mode(ignore_errors=True)
    channel_map = {'dev': _channel('test')}
    repoman = MagicMock()
    repoman.promote.return_value = iter([])

    with patch('rbbuild.promote.term'):
        promote.do_promote(
            ['dev:bad-1.0', 'dev:mypkg-1.0'], channel_map, 0, 2,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    assert call_count == 2


# With ignore_errors=False a SyntaxError is re-raised immediately.
def test_do_promote_ignore_errors_false_raises():
    promote = PromoteMain()
    deps_parser = MagicMock()
    deps_parser.parse_item.side_effect = SyntaxError('bad manifest')
    op_mode = _op_mode(ignore_errors=False)

    with patch('rbbuild.promote.term'):
        with pytest.raises(SyntaxError):
            promote.do_promote(
                ['dev:bad-1.0'], {}, 0, 1,
                deps_parser=deps_parser,
                resolver=MagicMock(),
                repoman=MagicMock(),
                op_mode=op_mode,
            )


# n_start or n_end out of bounds raises RuntimeError.
def test_do_promote_invalid_range():
    promote = PromoteMain()
    op_mode = _op_mode()
    with pytest.raises(RuntimeError, match='Invalid range'):
        promote.do_promote(
            ['pkg-1.0'], {}, 0, 5,   # n_end > len(qpkglist)
            deps_parser=MagicMock(),
            resolver=MagicMock(),
            repoman=MagicMock(),
            op_mode=op_mode,
        )


# resolver.run() no longer raises for a resolution problem (it's reported via
# ResolveResult.problems); with ignore_errors=True that problem is treated
# just like a manifest SyntaxError - logged and skipped, loop continues.
def test_do_promote_resolution_problem_ignore_errors_continues():
    promote = PromoteMain()
    pkg = _pkg('mypkg', '1.0', 'dev')
    channel_map = {'dev': _channel('test')}

    resolver = MagicMock()
    resolver.run.side_effect = [
        ResolveResult(packages={}, problems=['Could not resolve bad-1.0']),
        ResolveResult(packages={repr(pkg): pkg}, problems=[]),
    ]

    deps_parser = _deps_parser(pkg)
    repoman = MagicMock()
    repoman.promote.return_value = iter([])
    op_mode = _op_mode(ignore_errors=True)

    with patch('rbbuild.promote.term'):
        promote.do_promote(
            ['dev:bad-1.0', 'dev:mypkg-1.0'], channel_map, 0, 2,
            deps_parser=deps_parser,
            resolver=resolver,
            repoman=repoman,
            op_mode=op_mode,
        )

    assert resolver.run.call_count == 2
    repoman.promote.assert_called_once_with(pkg=pkg, destination_channel=channel_map['dev'])


# Same as above, but with ignore_errors=False - the resolution problem must
# stop the whole batch (same contract as a manifest SyntaxError).
def test_do_promote_resolution_problem_ignore_errors_false_raises():
    promote = PromoteMain()
    channel_map = {'dev': _channel('test')}

    resolver = MagicMock()
    resolver.run.return_value = ResolveResult(packages={}, problems=['Could not resolve bad-1.0'])

    deps_parser = MagicMock()
    deps_parser.parse_item.return_value = _pkg('bad', '1.0', 'dev')
    repoman = MagicMock()
    op_mode = _op_mode(ignore_errors=False)

    with patch('rbbuild.promote.term'):
        with pytest.raises(Exception, match='Could not resolve bad-1.0'):
            promote.do_promote(
                ['dev:bad-1.0'], channel_map, 0, 1,
                deps_parser=deps_parser,
                resolver=resolver,
                repoman=repoman,
                op_mode=op_mode,
            )

    repoman.promote.assert_not_called()



# ---------------------------------------------------------------------------
# main — channel map string parsing
# ---------------------------------------------------------------------------

def _channels_config():
    return {
        'dev':     {'type': 'rbbuild', 'remote_service': 'svc', 'repository': 'repo-dev',     'root_path': ''},
        'test':    {'type': 'rbbuild', 'remote_service': 'svc', 'repository': 'repo-test',    'root_path': ''},
        'staging': {'type': 'rbbuild', 'remote_service': 'svc', 'repository': 'repo-staging', 'root_path': ''},
        'prod':    {'type': 'rbbuild', 'remote_service': 'svc', 'repository': 'repo-prod',    'root_path': ''},
    }


# Channel map -m dev:test is resolved into Channel objects keyed by source name.
def test_main_channel_map_parsed(monkeypatch):
    promote = PromoteMain()
    args = parse_command_line(['-m', 'dev:test', 'mypkg-1.0'])

    captured_channel_map = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_channel_map.update(channel_map)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)

    promote.main(args, channels_config=_channels_config())

    assert 'dev' in captured_channel_map
    assert captured_channel_map['dev'].name == 'test'


# Source == target raises RuntimeError.
def test_main_channel_map_same_channel_raises(monkeypatch):
    promote = PromoteMain()
    args = parse_command_line(['-m', 'dev:dev', 'mypkg-1.0'])
    with pytest.raises(RuntimeError, match='same'):
        promote.main(args, channels_config=_channels_config())


# Neither -m nor -M → RuntimeError.
def test_main_no_channel_map_raises():
    promote = PromoteMain()
    args = parse_command_line(['mypkg-1.0'])
    with pytest.raises(RuntimeError, match='no channel mapping'):
        promote.main(args, channels_config=_channels_config())


# Unknown source channel name raises RuntimeError.
def test_main_unknown_source_channel_raises():
    promote = PromoteMain()
    args = parse_command_line(['-m', 'nonexistent:test', 'mypkg-1.0'])
    with pytest.raises(RuntimeError, match='Failed to resolve channel nonexistent'):
        promote.main(args, channels_config=_channels_config())


# Unknown target channel name raises RuntimeError.
def test_main_unknown_target_channel_raises():
    promote = PromoteMain()
    args = parse_command_line(['-m', 'dev:nonexistent', 'mypkg-1.0'])
    with pytest.raises(RuntimeError, match='Failed to resolve channel nonexistent'):
        promote.main(args, channels_config=_channels_config())


# Map file with text lines (not JSON) is parsed correctly (bug fix: used 'mapping' not 'line').
def test_main_map_file_text_parsing(tmp_path, monkeypatch):
    map_file = tmp_path / 'channels.txt'
    map_file.write_text('dev:test\n')

    promote = PromoteMain()
    args = parse_command_line(['-M', str(map_file), 'mypkg-1.0'])

    captured_channel_map = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_channel_map.update(channel_map)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
    promote.main(args, channels_config=_channels_config())

    assert 'dev' in captured_channel_map
    assert captured_channel_map['dev'].name == 'test'


# Map file in JSON format is parsed correctly.
def test_main_map_file_json_parsing(tmp_path, monkeypatch):
    map_file = tmp_path / 'channels.json'
    map_file.write_text(json.dumps({'dev': 'test'}))

    promote = PromoteMain()
    args = parse_command_line(['-M', str(map_file), 'mypkg-1.0'])

    captured_channel_map = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_channel_map.update(channel_map)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
    promote.main(args, channels_config=_channels_config())

    assert 'dev' in captured_channel_map


# A non-existent -M file raises RuntimeError.
def test_main_missing_map_file_raises():
    promote = PromoteMain()
    args = parse_command_line(['-M', '/nonexistent/path.txt', 'mypkg-1.0'])
    with pytest.raises(RuntimeError, match='does not exists'):
        promote.main(args, channels_config=_channels_config())


# Multiple comma-separated mappings in -m are all resolved.
def test_main_multiple_channel_map_entries(monkeypatch):
    promote = PromoteMain()
    args = parse_command_line(['-m', 'dev:test,staging:prod', 'mypkg-1.0'])

    captured_channel_map = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_channel_map.update(channel_map)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
    promote.main(args, channels_config=_channels_config())

    assert 'dev' in captured_channel_map
    assert captured_channel_map['dev'].name == 'test'
    assert 'staging' in captured_channel_map
    assert captured_channel_map['staging'].name == 'prod'


# ---------------------------------------------------------------------------
# main — --input-file (-i) reads packages line-by-line
# ---------------------------------------------------------------------------

# -i reads each non-empty line as a package entry.
def test_main_input_file_reads_lines(tmp_path, monkeypatch):
    pkg_file = tmp_path / 'packages.txt'
    pkg_file.write_text('dev:pkgA-1.0\ndev:pkgB-2.0\n')

    promote = PromoteMain()
    args = parse_command_line(['-i', str(pkg_file), '-m', 'dev:test'])

    captured_list = []

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_list.extend(qpkglist)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
    with patch('rbbuild.promote.term'):
        promote.main(args, channels_config=_channels_config())

    assert captured_list == ['dev:pkgA-1.0', 'dev:pkgB-2.0']


# Empty lines in the input file are ignored.
def test_main_input_file_ignores_empty_lines(tmp_path, monkeypatch):
    pkg_file = tmp_path / 'packages.txt'
    pkg_file.write_text('\ndev:pkgA-1.0\n\ndev:pkgB-2.0\n\n')

    promote = PromoteMain()
    args = parse_command_line(['-i', str(pkg_file), '-m', 'dev:test'])

    captured_list = []

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured_list.extend(qpkglist)

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
    with patch('rbbuild.promote.term'):
        promote.main(args, channels_config=_channels_config())

    assert captured_list == ['dev:pkgA-1.0', 'dev:pkgB-2.0']


# ---------------------------------------------------------------------------
# main — --range parsing
# ---------------------------------------------------------------------------

# --range 1-3 passes n_start=1, n_end=3 to do_promote.
def test_main_range_start_end(monkeypatch):
    promote = PromoteMain()
    args = parse_command_line(['-m', 'dev:test', '--range', '1-3', 'ignored'])
    args.package = None
    # Simulate an input list via input_list_file by patching do_promote and
    # providing a fake qpkglist through monkeypatching do_promote directly.

    captured = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured['n_start'] = n_start
        captured['n_end'] = n_end

    monkeypatch.setattr(promote, 'do_promote', fake_do_promote)

    # Inject a pre-built package list by using -i
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for i in range(5):
            f.write(f'dev:pkg{i}-1.0\n')
        fname = f.name
    try:
        args2 = parse_command_line(['-i', fname, '-m', 'dev:test', '--range', '1-3'])
        monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
        with patch('rbbuild.promote.term'):
            promote.main(args2, channels_config=_channels_config())
    finally:
        os.unlink(fname)

    assert captured['n_start'] == 1
    assert captured['n_end'] == 3


# --range 2- passes n_start=2, n_end=<full length>.
def test_main_range_open_end(monkeypatch):
    promote = PromoteMain()
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for i in range(5):
            f.write(f'dev:pkg{i}-1.0\n')
        fname = f.name

    captured = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured['n_start'] = n_start
        captured['n_end'] = n_end

    try:
        args = parse_command_line(['-i', fname, '-m', 'dev:test', '--range', '2-'])
        monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
        with patch('rbbuild.promote.term'):
            promote.main(args, channels_config=_channels_config())
    finally:
        os.unlink(fname)

    assert captured['n_start'] == 2
    assert captured['n_end'] == 5  # full length


# --range -3 passes n_start=0, n_end=3.
def test_main_range_open_start(monkeypatch):
    promote = PromoteMain()
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for i in range(5):
            f.write(f'dev:pkg{i}-1.0\n')
        fname = f.name

    captured = {}

    def fake_do_promote(qpkglist, channel_map, n_start, n_end, tag=False, **kw):
        captured['n_start'] = n_start
        captured['n_end'] = n_end

    try:
        args = parse_command_line(['-i', fname, '-m', 'dev:test', '--range', '-3'])
        monkeypatch.setattr(promote, 'do_promote', fake_do_promote)
        with patch('rbbuild.promote.term'):
            promote.main(args, channels_config=_channels_config())
    finally:
        os.unlink(fname)

    assert captured['n_start'] == 0
    assert captured['n_end'] == 3


# ---------------------------------------------------------------------------
# RepositoryManager.promote() — copy logic
# ---------------------------------------------------------------------------

# Minimal stand-in for an Artifactory service used in promote tests.
class _FakeService:
    def __init__(self, url, tmpdir=None):
        self.url = url
        self.tmpdir = tmpdir
        self.copy = MagicMock(return_value=True)
        self.upload_component = MagicMock()
        self.manifest = MagicMock()


    def can_copy_to(self, other):
        return type(self) is type(other) and self.url == other.url


    def resource_url(self, pkg: Package):
        return f'{self.url}{pkg.name}-{pkg.version}'


# A DIFFERENT service type (simulates a different server type).
class _FakeServiceB(_FakeService):
    pass


# Build a minimal RepositoryManager without triggering __init__.
def _make_repoman(src_service, dst_service, src_channel, dst_channel):
    repoman = RepositoryManager.__new__(RepositoryManager)
    repoman.service = lambda ch: src_service if ch is src_channel else dst_service
    repoman.download = MagicMock(return_value=iter([]))
    return repoman


def _make_pkg_with_components(channel, *comp_filenames):
    pkg = Package(name='mypkg', version='1.0')
    pkg.channel = channel
    pkg.components = [
        Component(name='mypkg', suffix='tar', filename=fn, checksum='abc')
        for fn in comp_filenames
    ]
    pkg.toolchain = None
    pkg.dependencies = {}
    pkg.tools = []
    return pkg


# Same-URL Artifactory services use server-side copy for each component.
def test_repoman_promote_same_server_uses_copy(tmp_path):
    src_ch = _channel('dev')
    dst_ch = _channel('test')
    shared_url = 'https://artifactory.example.com/'

    src_svc = _FakeService(url=shared_url)
    dst_svc = _FakeService(url=shared_url, tmpdir=tmp_path)
    dst_svc.manifest.from_package.return_value = {}
    dst_svc.manifest.make_filename.return_value = 'mypkg-1.0-manifest.json'

    pkg = _make_pkg_with_components(src_ch, 'mypkg-1.0-linux-native.tar.xz')

    repoman = _make_repoman(src_svc, dst_svc, src_ch, dst_ch)
    results = list(repoman.promote(pkg, dst_ch))

    src_svc.copy.assert_called_once_with(
        localfile=Path('mypkg-1.0-linux-native.tar.xz'),
        name='mypkg',
        version='1.0',
        source_channel=src_ch,
        destination_channel=dst_ch,
        sha1sum='abc',
    )
    dst_svc.upload_component.assert_called_once()  # manifest upload
    # First result = component (copied), last = manifest component
    assert results[0] is pkg.components[0]
    assert results[-1].suffix == 'json'


# copy() returning False (already exists) yields None for that component.
def test_repoman_promote_same_server_skipped_yields_none(tmp_path):
    src_ch = _channel('dev')
    dst_ch = _channel('test')
    url = 'https://artifactory.example.com/'

    src_svc = _FakeService(url=url)
    src_svc.copy.return_value = False   # skipped
    dst_svc = _FakeService(url=url, tmpdir=tmp_path)
    dst_svc.manifest.from_package.return_value = {}
    dst_svc.manifest.make_filename.return_value = 'mypkg-1.0-manifest.json'

    pkg = _make_pkg_with_components(src_ch, 'mypkg-1.0-linux-native.tar.xz')

    repoman = _make_repoman(src_svc, dst_svc, src_ch, dst_ch)
    results = list(repoman.promote(pkg, dst_ch))

    assert results[0] is None   # component was skipped


# The regenerated manifest reflects the destination channel name and URL.
def test_repoman_promote_manifest_updated_with_dst_channel(tmp_path):
    src_ch = _channel('dev')
    dst_ch = _channel('test')
    url = 'https://artifactory.example.com/'

    src_svc = _FakeService(url=url)
    dst_svc = _FakeService(url=url, tmpdir=tmp_path)
    dst_svc.manifest.from_package.return_value = {}
    dst_svc.manifest.make_filename.return_value = 'mypkg-1.0-manifest.json'

    pkg = _make_pkg_with_components(src_ch, 'mypkg-1.0-linux-native.tar.xz')
    pkg.url = 'https://artifactory.example.com/dev-local/components/mypkg-1.0'

    repoman = _make_repoman(src_svc, dst_svc, src_ch, dst_ch)
    list(repoman.promote(pkg, dst_ch))

    # from_package() must be called with a pkg whose channel is the destination
    # and whose URL is built from the destination service (not the source)
    (pkg_arg,), _ = dst_svc.manifest.from_package.call_args
    assert pkg_arg.channel is dst_ch
    assert pkg_arg.url.startswith(dst_svc.url)
    assert 'mypkg-1.0' in pkg_arg.url


# Different service types fall back to download + upload.
def test_repoman_promote_cross_server_uses_download_upload(tmp_path):
    src_ch = _channel('dev')
    dst_ch = _channel('test')

    src_svc = _FakeService(url='https://artifactory-a.example.com/')
    dst_svc = _FakeServiceB(url='https://artifactory-b.example.com/', tmpdir=tmp_path)
    dst_svc.manifest.from_package.return_value = {}
    dst_svc.manifest.make_filename.return_value = 'mypkg-1.0-manifest.json'

    local_comp = Component(name='mypkg', suffix='tar', filename='mypkg-1.0-linux-native.tar.xz',
                           localpath=tmp_path / 'mypkg-1.0-linux-native.tar.xz')

    pkg = _make_pkg_with_components(src_ch, 'mypkg-1.0-linux-native.tar.xz')

    repoman = _make_repoman(src_svc, dst_svc, src_ch, dst_ch)
    repoman.download = MagicMock(return_value=iter([local_comp]))

    results = list(repoman.promote(pkg, dst_ch))

    src_svc.copy.assert_not_called()
    dst_svc.upload_component.assert_called()
    assert results[0] is pkg.components[0]


# A service that cannot copy to the destination falls back to download + upload.
def test_repoman_promote_uses_download_upload_if_copy_not_possible(tmp_path):
    src_ch = _channel('dev')
    dst_ch = _channel('test')
    url = 'https://s3.example.com/'

    src_svc = _FakeService(url=url)
    src_svc.can_copy_to = MagicMock(return_value=False)
    dst_svc = _FakeService(url=url, tmpdir=tmp_path)
    dst_svc.manifest.from_package.return_value = {}
    dst_svc.manifest.make_filename.return_value = 'mypkg-1.0-manifest.json'

    local_comp = Component(name='mypkg', suffix='tar', filename='mypkg-1.0-linux-native.tar.xz',
                           localpath=tmp_path / 'mypkg-1.0-linux-native.tar.xz')
    pkg = _make_pkg_with_components(src_ch, 'mypkg-1.0-linux-native.tar.xz')

    repoman = _make_repoman(src_svc, dst_svc, src_ch, dst_ch)
    repoman.download = MagicMock(return_value=iter([local_comp]))

    results = list(repoman.promote(pkg, dst_ch))

    src_svc.can_copy_to.assert_called_once_with(dst_svc)
    src_svc.copy.assert_not_called()
    assert results[0] is pkg.components[0]
