<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# Why rbbconf

*rbbconf* is a command-line tool for reading/writing settings
(e.g., access credentials) and querying project- or repository-specific
profile information.


# Profiles

A profile, identified by a unique name, is configuration container that
consists of:
* toolchain configuration
* remote service configuration (e.g., Artifactory or Jira)
* channels for downloading and uploading assets
* default settings (toolchain, channel, etc)

In this context, *channel* is an abstraction layer for representing
download or upload locations of packages. A local file folder
or PyPI repository can be represented as *channel*.

A *toolchain* is an abstraction for build toolchains. In rbbuild, they
originate from being a wrapper around CMake toolchain files, which allow
quick selecting different compiler targets and compiler flags.
Toolchains are represented as a string tuple *platform*-*toolchain-id*.

Profiles are usually shipped as a separate organization- or project-specific
bundle and are not part of rbbuild itself.

## File layout of configuration files

The configuration file structure uses the following path layout:

```
CONFIG_PATH
    |
    +- rbbuild.toml
    |
    +- profiles
         |
         +- standalone
              |
              +- standalone.toml
              |
              +- ruff.toml
              |
              +- remote-services/
              |    |
              |    +- *service-name*.toml
              |
              +- toolchains/
                   |
                   +- *platform*-*tcid*.toml
                   |
                   + cmake/
                       |
                       +- *platform*-*tcid*.cmake
```


Where CONFIG\_PATH is usually located in `share/rbbuild/config` within the
rbbuild virtual environment (venv).
User-specific configuration files are stored in `${HOME}/.config/rbbuild`.

If present in both, user configuration will have precedence over system
settings. Users can also override the `standalone` profile settings by providing
a copy of the profile. In this case, the standalone configuration from the rbbuild
installation will be completely ignored.

The profiles `standalone` and `test` are shipped with rbbuild.

### Builtin profile "standalone"

Unless otherwise specified in the user's configuration or `-P <profile>` is
passed via command-line, all rbbuild tools use the `standalone` profile by
default.
It contains a basic set of toolchains and provides the channel `local`, which
stores packages in `~/.cache/rbbuild/local` (created on the first publish).


### Builtin profile "test"

The main purpose of the `test` profile is to inject testable channels and toolchains.
With this profile, rbbuild projects can be tested using fake data from a local channel
under [test/data/fake_artifactory](../../test/data/fake_artifactory).

The contents of the `test` profile can be inspected with `pkq -P test -l` (see [pkq
documentation](pkq.md) for further options).

Consider the following basic `rbbuild.toml`:

```toml
[dependencies]
deps = ['testtool']
```

By calling `rbbuild -P test -FI`, the `testtool` component can be copied
and unpacked under `staging`.


### rbbuild.toml

Application settings for all rbbuild tools are stored here. The file shipped with rbbuild
(in the configuration path) defines the defaults, `~/.config/rbbuild/rbbuild.toml` overrides them.


| Section                      | Entry                        | Value (example)        | Comment                                                 |
|------------------------------|------------------------------|------------------------|---------------------------------------------------------|
| `[settings]`                 |                              |                        |                                                         |
|                              | profile                      | standalone             | Active profile. Override by `-P` or Jenkinsfile         |
|                              | toolchain-linux              | linux-yocto-armhf-4.0  | Default toolchain on Linux. Overrides the profile; `-t` and `RBB_TOOLCHAIN_ID` override it |
|                              | toolchain-win32              | win32-visualstudio-2022 | Default toolchain on Windows. Same rules as `toolchain-linux` |
| `[paths]`                    |                              |                        |                                                         |
|                              | user\_config                 | $HOME/.config/rbbuild  | Folder of the user configuration                        |
|                              | build\_root                  | obj                    | Build folder, relative to the source path               |
|                              | staging\_root                | staging                | Downloaded dependencies are extracted in this folder    |
|                              | documentation\_root          | obj                    | Documentation output, relative to the source path       |
|                              | dist                         | $HOME/.cache/rbbuild/dist | Download cache. Override by `RBB_DIST_PATH`          |
| `[tool.rbbuild]`             |                              |                        |                                                         |
|                              | actions                      | ['setup', 'build']     | Actions if rbbuild is called without parameters         |
|                              | build\_tools                 | ['rbbuild', 'cmake']   | Build tools that are considered                         |


### Profiles folder

In *rbbuild*, profiles define project-specific remote service settings and
defaults. Any folder underneath `profiles` will be considered as a profile if
a TOML file of the same name is present. For instance, if the file
`profiles/standalone/standalone.toml` exists, standalone will be considered as
a valid profile.

Profiles are provided by installed profile packages or by folders in the user
configuration, see [Managing Project Profiles](#managing-project-profiles).


#### *profile*/*profile*.toml


| Section                      | Entry                        | Value (example)                  | Comment                                                 |
|------------------------------|------------------------------|----------------------------------|---------------------------------------------------------|
| `[settings]`                 |                              |                                  | Top-level settings section                              |
|                              | channel                      | sample-development               | Default channel for all deps entries for this profile   |
|                              | profile\_version             | 1.0.0                            | Profile version. Should be bumped on every change       |
|                              | toolchain-linux              | linux-native                     | Default toolchain that is used on Linux                 |
|                              | toolchain-win32              | win32-visualstudio-2017          | Default toolchain that is used on Windows               |
| `[profile]`                  |                              |                                  | Optional                                                |
|                              | import                       | bosch                            | Takes over settings, channels, remote services and toolchains of another profile; entries of this profile override them |
| `[profile.supplier]`         |                              |                                  | Supplier of the profile and default supplier of packages built with it |
|                              | name                         | Example Corp                     | Required. Used as vendor of the profile in the SBOM tools section |
|                              | email                        | info@example.com                 | Optional. Default `package.supplier.email`              |
|                              | url                          | https://example.com/             | Optional. Default `package.supplier.url`                |
| `[profile.issuetracker.KEY]` |                              | `[profile.issuetracker.PROJ]`    | Multiple issue tracker services can be configured       |
|                              | remote\_service              | rb\_jira\_standard               | Reference to remote service name                        |
| `[profile.channels.NAME]`    |                              | `[profile.channels.development]` | See [Repository services](repository-services.md#channels) |
| `[profile.oss.NAME]`         |                              | `[profile.oss.project]`          | OSS scan service (see [rbfoss](rbfoss.md))              |
|                              | type                         | fossid                           | Required. Currently only fossid is supported            |
|                              | remote\_service              | rb\_fossid                       | Reference to remote service name                        |
|                              | project\_org\_prefix         | EXAMPLE                          | Prefix of the FossID project name                       |
|                              | users                        | ['jdoe']                         | FossID users that are granted access                    |
|                              | ignore\_files                | ['.gitignore']                   | Files that are not uploaded for scanning                |
|                              | ignore\_folders              | ['.git']                         | Folders that are not uploaded for scanning              |
| `[profile.ci.KEY]`           |                              | `[profile.ci.PROJECT]`           | Multiple CI services can be configured                  |
|                              | remote\_service              | rb\_jenkins                      | Reference to remote service name                        |
| `[profile.licensedb.NAME]`   |                              |                                  | NAME is the name of the profile                         |
|                              | remote\_service              | rb\_lml                          | Reference to remote service name                        |


#### *profile*/remote-services folder

This folder contains TOML files specifying remote services. The `remote-services` folder
of an installed configuration root is shared by all
profiles. A service of the same name in the profile's own `remote-services` folder
overrides the shared one.


| Section                      | Entry                        | Value (example)                  | Comment                                                 |
|------------------------------|------------------------------|----------------------------------|---------------------------------------------------------|
| `[profile.services.NAME]`    |                              | `[profile.services.git]`         |                                                         |
|                              | type                         | artifactory                      | Valid values: artifactory, s3, google\_drive, local\_file\_service, github, bitbucket, jira, jenkins, fossid, or a type provided by a plugin package |
|                              | url                          | https://path.to/                 | Service URL                                             |
|                              | auth-method                  | bearer-token                     | none (default), basic, bearer-token, or oauth2 (google\_drive only). See below |
|                              | truststore                   | true                             | (Optional) Verify TLS certificates with the operating system trust store. Default: false |
|                              | credentials                  | AKCp.....i9m                     | Used as APIKEY or password. Only in user config!        |
|                              | user                         | jdoe                             | (Optional) e.g., for services that rely on basic auth   |

For security reasons, *credentials* and *user* are not part of the profile. They are stored
in the `[service.NAME]` section of the user configuration (`~/.config/rbbuild/rbbuild.toml`),
where NAME is the name of the remote service.

The entry *auth-method* defines how rbbuild authenticates at the service, using the
*credentials* and *user* from the user credential store. If it is not defined, no
authentication is used (`none`). With `bearer-token`, the credentials are sent as bearer
token, or as basic authentication if a *user* is set. With `basic`, *user* and *credentials*
are sent as basic authentication.

With `truststore = true`, rbbuild verifies the TLS certificate of the service with the trust
store of the operating system (using the Python `truststore` module) instead of the CA bundle
shipped with Python. Use this for services that rely on corporate CA certificates.

The service types `artifactory`, `local_file_service`, `s3` and `google_drive`, and the settings of
channels are described in [Repository services](repository-services.md).

The remote service TOML file name can be freely chosen, however, it is good
practice to use `<service-name>.toml` as file name to avoid clashes with other
profiles.


#### *profile*/toolchains folder

A toolchain is defined by a TOML file in this folder. The file names need to match the
following pattern:

```
toolchains/<platform>-<tcid>.toml

with:
    <platform>: Operating system -- currently only "linux" and "win32" are supported
    <tcid>: Toolchain ID, e.g., native or yocto-armhf-2.4
```

By default, the CMake toolchain file of a toolchain is
`toolchains/cmake/<platform>-<tcid>.cmake`. rbbuild does not check whether the file exists
but passes the path to CMake, which fails if it is missing. A CMake file without a TOML
file is not a toolchain.

| Section                      | Entry                        | Value (example)                  | Comment                                                 |
|------------------------------|------------------------------|----------------------------------|---------------------------------------------------------|
| `[toolchain]`                |                              |                                  | Optional                                                |
|                              | native                       | true                             | The toolchain creates binaries for the system that runs rbbuild. Default: false |
| `[cmake]`                    |                              |                                  | Optional                                                |
|                              | file                         | cmake/common.cmake               | CMake toolchain file, relative to `toolchains`. Default: `cmake/<platform>-<tcid>.cmake` |
| `[python]`                   |                              |                                  | Optional                                                |
|                              | executable                   | python3.14                       | Python executable of the toolchain: an absolute path, or a name that is looked up in `PATH`. It must be available; rbbuild does not install it. Used for the staging venv (created by uv), the CMake call (`Python3_EXECUTABLE`) and the first entry of `PATH` for build processes. Default: Python of the rbbuild environment |
|                              | import                       | linux-cpython314                 | Takes over `executable` and `environment` of another toolchain of the profile; entries of this file override. Use it, e.g., for C/C++ toolchains that build extension modules for a Python toolchain |
| `[python.environment]`       |                              |                                  | Optional. Environment variables for processes that use the Python of the toolchain (uv, pytest, build tools) |
|                              | PYTHONPATH                   | /opt/python/lib                  | `PATH` and `PYTHONPATH` are prepended to the existing value; other variables are only set if not defined yet |
| `[wheel]`                    |                              |                                  | Optional                                                |
|                              | platform-tag                 | linux_armv7l                     | Platform tag of Python wheels with compiled code (`platform-specific` in [rbbuild.toml](rbbuild.toml.md)) |

For Python wheels with compiled code, the platform tag is taken from `platform-tag`. If it
is not defined, the tag of the running Python interpreter (e.g., `linux_x86_64`) is used
for `native` toolchains. For all other toolchains, the platform tag must be defined, or
`wheel-tag` must be set in the packaging entry.

## Setting user parameters (-s / --setconf)

Individual parameters can be set with *rbbconf*. Examples:

```shell
   # Set Artifactory user credentials for rb_artifactory service
   rbbconf -s service.rb_artifactory.user=<user ID>
   rbbconf -s service.rb_artifactory.credentials=<APIKEY>

   # Select the profile that is used by default
   rbbconf -s settings.profile=myprofile
```

Settings that are also defined by the selected profile (e.g., `channel`) are
overridden by the profile. The exception is the default toolchain
(`toolchain-<platform>`): a value in the user configuration overrides the profile.
It is only used by projects that need a toolchain (e.g., CMake) and for
dependencies without `toolchain=`; other projects use `none-any`.
The following calls are equivalent and store `toolchain-linux = 'linux-yocto-armhf-4.0'`:
```shell
   rbbconf -s toolchain-linux=linux-yocto-armhf-4.0
   rbbconf -s toolchain=linux-yocto-armhf-4.0
   rbbconf -s toolchain=yocto-armhf-4.0      # for the current platform
```

The following syntax is accepted for `rbbconf --setconf` (`-s` for short):
```
   rbbconf -s [<section>.]<key>=<value>
```
If `<section>` is not present, "settings" will be assumed.
For example, `rbbconf -s settings.profile=myprofile` can be abbreviated
to `rbbconf -s profile=myprofile`.

Multiple settings can be set with a single command as shown in the following
example:
```
   rbbconf -s profile=myprofile,service.rb_artifactory.user=jdoe
```


## List configuration parameters (-g / --getconf)

`rbbconf --getconf` (`-g` for short) prints out all sections and key value
pairs for the current configuration.

By passing the optional FILTER parameter, specific sections or keys can
be searched.

Examples:

```
# Print all settings
rbbconf -g

# Print profile configuration section
rbbconf -g "profiles"

# Print all keys for the rb_artifactory remote service
rbbconf -g "service.rb_artifactory"

# Print all channel definitions
rbbconf -g "profile.channels.*"

# Print all keys starting with toolchain in settings section
rbbconf -g "settings.toolchain*"

# Wildcards may also be placed in the middle
rbbconf -g profile.services.*.url
```

By adding `--format=json`, rbbconf will generate the output in JSON format.
The argument `-o` or `--outfile` will write the output to the specified file
path instead of the current terminal's standard output.

Note that credentials and passwords will be obfuscated with `*` by default when
outfile is not specified.


# Managing Project Profiles

Profiles in rbbuild define a collection of settings for a specific project or a
group of projects.

With `rbbconf --list profiles` (or `-l profiles` for short), users can retrieve
the list of installed profiles. The currently selected profile will be marked
with a green `*` symbol.

Profiles are usually provided by installed profile packages. These register
themselves as configuration roots (entry-point group `rbbuild.config`, see the
developer manual), so that their profiles and the remote services shared by all
profiles are found without any further setup. In the list of profiles, such
profiles are marked as `plugin`.

A profile in the user configuration (`~/.config/rbbuild/profiles`) has
precedence over a profile of the same name from an installed package.
For instance, a profile folder of a source tree can be symlinked on Linux:

```shell
cd ~/.config/rbbuild/profiles
ln -s <path-to-source-tree>/<package>/profiles/<profile> .
```

In this example, the profile from the source tree will be used. The profile of
the same name from the installed package will be ignored.

