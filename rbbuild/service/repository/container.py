# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from dependency_injector import containers, providers

from .artifactory import Artifactory
from .google_drive import GoogleDrive
from .local_file_storage import LocalFileStorage, LocalFileService
from .manager import RepositoryManager
from .plugins import load_repository_plugins
from .s3 import S3
from .url_service import URLService


# Plugin Repository classes are constructed like the built-in services
# (see RepositoryManager.service).
def _plugin_providers(config, core, package) -> dict:
    return {
        name: providers.Factory(
            cls,
            manifest    = package.manifest,
            temp_folder = core.temp_folder,
            op_mode     = config.op_mode,
        ).provider
        for name, cls in load_repository_plugins().items()
    }


class RepositoryContainer(containers.DeclarativeContainer):
    config  = providers.Configuration()
    core    = providers.DependenciesContainer()
    deps    = providers.DependenciesContainer()
    package = providers.DependenciesContainer()

    local_file_storage = providers.Factory(
        LocalFileStorage,
        dist_path = config.paths.dist,
        manifest = package.manifest,
    )

    local_file_service = providers.Factory(
        LocalFileService,
        manifest = package.manifest,
        temp_folder = core.temp_folder,
        op_mode     = config.op_mode,
    )

    artifactory = providers.Factory(
        Artifactory,
        manifest = package.manifest,
        temp_folder = core.temp_folder,
        op_mode     = config.op_mode,
    )

    url = providers.Factory(
        URLService,
        manifest = package.manifest,
        temp_folder = core.temp_folder,
    )

    s3 = providers.Factory(
        S3,
        manifest    = package.manifest,
        temp_folder = core.temp_folder,
        op_mode     = config.op_mode,
    )

    google_drive = providers.Factory(
        GoogleDrive,
        manifest    = package.manifest,
        temp_folder = core.temp_folder,
        op_mode     = config.op_mode,
    )

    # https://refactoring.guru/design-patterns/facade
    repoman = providers.Singleton(
        RepositoryManager,
        deps_parser        = deps.parser,
        selected_channel   = core.channel,
        target_toolchain   = core.target_toolchain,
        op_mode            = config.op_mode,
        cache_provider     = local_file_storage.provider,
        services_config    = config.profile.services,
        user_config        = config.service,  # user overrides and credentials
        toolchains_config  = config.profile.toolchains,
        # **providers (Repository factories); plugin types take precedence
        **{
            'artifactory':        artifactory.provider,
            'local_file_service': local_file_service.provider,
            's3':                 s3.provider,
            'google_drive':       google_drive.provider,
            'url':                url.provider,
            **_plugin_providers(config, core, package),
        },
    )

