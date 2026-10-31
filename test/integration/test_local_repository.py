# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import pytest
import shutil
import sys

_TOOLCHAIN_ID = 'win32-mingw' if sys.platform == 'win32' else 'linux-native'

_skip_without_toolchain = pytest.mark.skipif(
    shutil.which('cmake') is None,
    reason='cmake not available in PATH',
)


# The local repository does not exist until the first publish
def test_missing_repository_is_empty(pkq_empty, user_home_empty):
    pkq_empty.run(['-l'])
    assert 'Packages in channel local' in pkq_empty.read_console()

    with pytest.raises(RuntimeError):
        pkq_empty.run(['-l', 'nopkg'])

    assert not (user_home_empty / '.cache/rbbuild/local').exists()


@_skip_without_toolchain
@pytest.mark.parametrize('spaces_in_path', [False, True])
def test_publish_and_list(
    rbbuild_empty, pkq_empty, user_home_empty, spaces_in_path,
):
    if spaces_in_path:
        workdir = (rbbuild_empty.workdir.parent / 'checkout with spaces'
                   / 'project')
        workdir.mkdir(parents=True)
        rbbuild_empty.workdir = workdir
    (rbbuild_empty.workdir / 'main.cc').write_text('int main() {return 0;}')

    rbbuild_empty.run(['-g', '.'])
    rbbuild_empty.run(['-sbp'])
    rbbuild_empty.run(['--publish', 'local'])

    repo = user_home_empty / '.cache/rbbuild/local/default/components/project'
    versions = [*repo.iterdir()]
    assert len(versions) == 1
    published = sorted(f.name for f in versions[0].iterdir())
    assert any(name.endswith('-manifest.json') for name in published)

    pkq_empty.run(['-l'])
    assert '[*] project' in pkq_empty.read_console()
