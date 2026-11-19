#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

import os
from typing import Optional

from rbbuild.service.remote_service import AuthMethod

from .manager import CIService


class Jenkins(CIService):
    def __init__(
        self,
        key: str,
        url: str,
        auth_method: AuthMethod,
        user: str,
        credentials: str,
        truststore: bool,
    ):
        CIService.__init__(
            self,
            key=key,
            url=url,
            auth_method=auth_method,
            user=user,
            credentials=credentials,
            truststore=truststore,
        )


    def job_url(self) -> Optional[str]:
        return os.environ.get('BUILD_URL')
