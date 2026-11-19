# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

from dependency_injector import containers, providers

from .diff import PackageDiff
from .manifest import Manifest
from .metadata import Metadata
from .parser import ManifestJSONParser


class PackageContainer(containers.DeclarativeContainer):
    config = providers.Configuration()
    core   = providers.DependenciesContainer()

    metadata = providers.Factory(
        Metadata,
        project_config = config.project,
        paths          = core.paths,
        toolchain      = core.toolchain,
        development    = core.channel.provided.development,
    )

    parser = providers.Singleton(
        ManifestJSONParser,
        channel_factory   = core.channel_factory,
        toolchain_factory = core.toolchain_factory,
    )
    manifest = providers.Singleton(
        Manifest,
        manifest_parser = parser,
    )
    diff = providers.Factory(
        PackageDiff,
        diffmode=config.diffmode,
        filter_changes=config.filter_changes,
    )

