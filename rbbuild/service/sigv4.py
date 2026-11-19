# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import hashlib
import hmac

from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, urlsplit

from requests.auth import AuthBase


EMPTY_PAYLOAD_SHA256 = hashlib.sha256(b'').hexdigest()

# Headers other than host and x-amz-* that are signed if present
_SIGNED_HEADERS = ('content-md5', 'content-type', 'range')


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


# AWS Signature Version 4 for S3 requests. Streamed request bodies must
# carry their x-amz-content-sha256 header already.
class SigV4Auth(AuthBase):
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        region: str,
        service: str = 's3',
    ):
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._service = service


    # now is only passed by tests
    def __call__(self, r, now: datetime = None):
        now = now or datetime.now(timezone.utc)
        amzdate = now.strftime('%Y%m%dT%H%M%SZ')
        datestamp = amzdate[:8]

        url = urlsplit(r.url)
        r.headers['x-amz-date'] = amzdate
        if 'x-amz-content-sha256' not in r.headers:
            if r.body is None:
                payload_hash = EMPTY_PAYLOAD_SHA256
            elif isinstance(r.body, bytes):
                payload_hash = hashlib.sha256(r.body).hexdigest()
            else:
                raise ValueError('x-amz-content-sha256 is required for streamed bodies')
            r.headers['x-amz-content-sha256'] = payload_hash
        payload_hash = r.headers['x-amz-content-sha256']

        headers = {'host': url.netloc}
        for name, value in r.headers.items():
            lname = name.lower()
            if lname.startswith('x-amz-') or lname in _SIGNED_HEADERS:
                headers[lname] = ' '.join(str(value).split())
        signed_headers = ';'.join(sorted(headers))
        canonical_headers = ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers))

        query = sorted(
            (quote(k, safe='-_.~'), quote(v, safe='-_.~'))
            for k, v in parse_qsl(url.query, keep_blank_values=True)
        )
        canonical_query = '&'.join(f'{k}={v}' for k, v in query)

        canonical_request = '\n'.join([
            r.method,
            url.path or '/',
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ])

        scope = f'{datestamp}/{self._region}/{self._service}/aws4_request'
        string_to_sign = '\n'.join([
            'AWS4-HMAC-SHA256',
            amzdate,
            scope,
            hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
        ])

        key = _hmac(('AWS4' + self._secret_key).encode('utf-8'), datestamp)
        for part in (self._region, self._service, 'aws4_request'):
            key = _hmac(key, part)
        signature = hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        r.headers['Authorization'] = (
            f'AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, '
            f'SignedHeaders={signed_headers}, Signature={signature}'
        )
        return r
