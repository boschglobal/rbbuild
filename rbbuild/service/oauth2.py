# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import time

import requests

from requests.auth import AuthBase


# Seconds before expiry at which the access token is refreshed
_EXPIRY_MARGIN = 60


# Sends a bearer token obtained with an OAuth 2.0 refresh token, and
# refreshes it when it has expired.
class OAuth2RefreshAuth(AuthBase):
    def __init__(
        self,
        session: requests.Session,
        token_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ):
        self._session = session
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token = None
        self._expires_at = 0.0


    def __call__(self, r):
        if not self._access_token or time.monotonic() >= self._expires_at:
            self._refresh()
        r.headers['Authorization'] = f'Bearer {self._access_token}'
        return r


    def _refresh(self):
        resp = self._session.post(
            self._token_url,
            data={
                'grant_type': 'refresh_token',
                'client_id': self._client_id,
                'client_secret': self._client_secret,
                'refresh_token': self._refresh_token,
            },
        )
        if not resp.ok:
            try:
                detail = resp.json().get('error_description') or resp.json().get('error')
            except ValueError:
                detail = None
            raise RuntimeError(
                f'OAuth2 token refresh failed (HTTP {resp.status_code})'
                + (f': {detail}' if detail else '')
            )

        data = resp.json()
        self._access_token = data['access_token']
        self._expires_at = time.monotonic() + int(data.get('expires_in', 3600)) - _EXPIRY_MARGIN
