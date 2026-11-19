# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import hashlib

def compute_sha1sum(fname):
    hashf = hashlib.sha1()
    block_size = 65536
    with open(fname, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b''):
            hashf.update(block)
    return hashf.hexdigest()


def compute_sha256sum(fname):
    hashf = hashlib.sha256()
    block_size = 65536
    with open(fname, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b''):
            hashf.update(block)
    return hashf.hexdigest()


def compute_sha512sum(fname):
    hashf = hashlib.sha512()
    block_size = 65536
    with open(fname, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b''):
            hashf.update(block)
    return hashf.hexdigest()

