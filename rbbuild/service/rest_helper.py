# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import os
import requests

from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from rbbuild.librbb.term import term


class RESTHelper:
    def __init__(
        self,
        tmpdir: Path,
        session: requests.Session,
        progress_cb: Callable[[int, int], None] = term.print_download_progress,
    ):
        self.tmpdir = tmpdir
        self.CHUNK_BLOCK_SIZE = 65536
        self.progress_cb = progress_cb
        self.session = session


    def download_file(
        self,
        url: str,
        headers: dict,
        auth,
        missing_ok: bool = False,
    ) -> Optional[Path]:
        if not url:
            raise RuntimeError('Cannot download file (url missing)')

        urlp = urlparse(url)
        localfile = self.tmpdir / Path(urlp.path).name

        with self.session.get(url=url, headers=headers, auth=auth, stream=True) as resp:
            if not resp.ok:
                localfile.unlink(missing_ok=True)
                if missing_ok and resp.status_code == 404:
                    return None
                resp.raise_for_status()
            total_len = int(resp.headers.get('Content-Length', 0))
            nwritten = 0
            with open(localfile, 'wb') as fd:
                for chunk in resp.iter_content(chunk_size=self.CHUNK_BLOCK_SIZE):
                    nwritten += len(chunk)
                    fd.write(chunk)
                    self.progress_cb(nwritten, total_len)

        return localfile


    def upload_file(
        self,
        localfile: Path,
        checksum: str,
        url: str,
        headers: dict,
        auth,
    ):
        def _chunked_file_reader(fd, chunk_block_size):
            total_len = os.fstat(fd.fileno()).st_size
            nread = 0
            while True:
                chunk = fd.read(chunk_block_size)
                if not chunk:
                    break
                nread += len(chunk)

                self.progress_cb(nread, total_len)

                yield chunk

        with open(localfile, 'rb') as fd:
            resp = self.session.put(
                url=url,
                headers=headers,
                auth=auth,
                data=_chunked_file_reader(fd, self.CHUNK_BLOCK_SIZE),
            )
            resp.raise_for_status()

