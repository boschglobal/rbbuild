<!--
SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
SPDX-FileContributor: Tolga Dalman

SPDX-License-Identifier: MIT
-->

# Repository services

Packages are stored in repositories. rbbuild supports these repository service types:

| Type | Storage | Channel types | Authentication (`auth-method`) | Server-side copy by *promote* |
|------|---------|---------------|--------------------------------|-------------------------------|
| `artifactory` | JFrog Artifactory | `rbbuild`, `plain`, `pypi` | `none`, `basic`, `bearer-token` | yes |
| `local_file_service` | Folder in the file system | `rbbuild` | `none` | no (download and upload) |
| `s3` | Amazon S3 and S3-compatible services | `rbbuild`, `plain` | not used (AWS Signature Version 4) | yes |
| `google_drive` | Google Drive (My Drive, Shared Drive) | `rbbuild`, `plain` | `oauth2` | yes |

Three parts configure a repository:

| Part | Location | Content |
|------|----------|---------|
| Remote service | `[profile.services.NAME]` in the profile (`remote-services` folder) | Type, URL and other settings that are not secret |
| Channel | `[profile.channels.NAME]` in the profile | Where in the service the packages are stored |
| Credentials | `[service.NAME]` in the user configuration (`~/.config/rbbuild/rbbuild.toml`) | Everything that identifies the user. Never part of the profile |

NAME of the credentials is the name of the remote service. For general information on profiles,
channels and remote services, see [rbbconf](rbbconf.md).


## Common settings

### Channels

A channel selects a location in a remote service. Its entries in `[profile.channels.NAME]` are:

| Entry | Comment |
|-------|---------|
| `type` | Content of the channel (see below) |
| `remote_service` | Reference to the remote service |
| `repository` | Container of the packages, e.g., a repository or bucket. See the service types below |
| `root_path` | (Optional) Path in the repository. Packages are stored in `<root_path>/<name>/<version>/` |
| `redirect_repos` | (Optional, type `rbbuild`) Names of channels that are searched if a package is not found |
| `permissions` | (Optional) Highest operation that is allowed: `read`, `upload`, `overwrite` or `delete` (default). Publishing needs at least `upload`, deleting needs `delete`. Currently, `overwrite` is handled like `upload` |
| `publish` | (Optional) `false` disables publishing to the channel, unless `--force` is used. Default: true |
| `development` | (Optional) `true` marks the channel for development packages, whose versions get a `.devN` suffix. Default: false |
| `branch_pattern` | (Optional) List of patterns, e.g., `['develop', 'feature/*']`. If no channel is selected, the channel whose pattern matches the current git branch is used instead of the default channel |

The channel types are:

* `rbbuild`: packages built by rbbuild. Each package version has a `manifest.json` per
  toolchain next to its component files, see
  [Versioning and Artifactory Mapping](../developer-manual/architecture.md).
* `plain`: arbitrary files. The manifest is generated from the files of the version folder.
* `pypi`: PyPI repository (Artifactory only). Like `plain`, the manifest is generated.
* A type provided by a plugin package.

### Authentication

Credentials are only read from the user configuration (`[service.NAME]`), where they can be set
with `rbbconf` or `RBB_CREDENTIALS` (see [rbbconf](rbbconf.md) and [rbbuild](rbbuild.md)).
The remote service entries `auth-method` and `truststore` are described in
[rbbconf](rbbconf.md#profileremote-services-folder).

### Caching, publishing and promotion

All downloaded manifests and components are cached in the dist path, see
[Artifactory caching and the dist path](rbbuild.md#artifactory-caching-and-the-dist-path).
This works the same for all service types.

Publishing a version that already exists in the channel is a version conflict for all service
types, see [Version folders](../developer-manual/architecture.md#version-folders).

[promote](promote.md) copies packages inside the service if the source and destination channel
use the same service type and URL. Otherwise, each component is downloaded and uploaded to the
destination.


## Artifactory

A service of type `artifactory` uses the REST API of a JFrog Artifactory server.

Remote service (profile):

```toml
[profile.services.rb_artifactory]
type        = 'artifactory'
auth-method = 'bearer-token'
url         = 'https://artifactory.example.com/artifactory/'
```

Channel (profile):

```toml
[profile.channels.sample-development]
type           = 'rbbuild'
remote_service = 'rb_artifactory'
repository     = 'sample-development-local'
root_path      = 'components'
```

Credentials (user configuration):

```toml
[service.rb_artifactory]
user        = 'jdoe'
credentials = 'AKCp...'
```

| Entry | Where | Comment |
|-------|-------|---------|
| `url` | service | Base URL of Artifactory, including the trailing slash |
| `repository` | channel | Artifactory repository key |
| `user` | user config | (Optional) User ID. With `bearer-token`, credentials are sent as basic authentication if a user is set |
| `credentials` | user config | API key, identity token or password |


## Local file service

A service of type `local_file_service` stores packages in a folder, for example on the local
disk or on a network share. It is used by the `standalone` profile and is handy for offline
work and for tests.

Remote service (profile):

```toml
[profile.services.local]
type        = 'local_file_service'
auth-method = 'none'
url         = 'file:$HOME/.cache/rbbuild'
```

Channel (profile):

```toml
[profile.channels.local]
type           = 'rbbuild'
remote_service = 'local'
repository     = 'default'
root_path      = 'components'
```

| Entry | Where | Comment |
|-------|-------|---------|
| `url` | service | `file:` followed by the base folder. Environment variables are expanded |
| `repository` | channel | Folder below the folder of the service |

The packages of the channel above are stored in
`$HOME/.cache/rbbuild/local/default/components/<name>/<version>/`, i.e., the folder is
`<path of url>/<name of remote service>/<repository>/<root_path>`. It is created on the first
publish. No credentials are needed.


## Amazon S3 and S3-compatible services

A service of type `s3` stores packages in a bucket. Buckets are addressed by path
(`<url>/<bucket>/<key>`), which AWS and S3-compatible services such as MinIO support.

Remote service (profile):

```toml
[profile.services.my_s3]
type   = 's3'
url    = 'https://s3.eu-central-1.amazonaws.com/'
region = 'eu-central-1'
```

Channel (profile):

```toml
[profile.channels.mys3]
type           = 'rbbuild'
remote_service = 'my_s3'
repository     = 'my-bucket'
root_path      = 'rbbuild/components'
```

Credentials (user configuration):

```toml
[service.my_s3]
user        = 'AKIA...'
credentials = 'wJalr...'
```

| Entry | Where | Comment |
|-------|-------|---------|
| `url` | service | Required. Endpoint of AWS or of a compatible service |
| `region` | service | (Optional) Region used to sign requests. Default: `us-east-1`, which most compatible services accept. AWS reports the expected region if it is wrong |
| `repository` | channel | Bucket name |
| `user` | user config | Access key ID. Required |
| `credentials` | user config | Secret access key. Required |

Requests are always signed with AWS Signature Version 4. Neither `~/.aws` nor the environment
variables of the AWS tools are read.


## Google Drive

A service of type `google_drive` stores packages in folders of My Drive or of a Shared
Drive. Authentication uses OAuth 2.0 (`auth-method = 'oauth2'`, required): rbbuild uses a refresh
token to obtain short-lived access tokens and sends them as bearer token.

Remote service (profile):

```toml
[profile.services.google_mydrive]
type        = 'google_drive'
auth-method = 'oauth2'
# drive-id  = '0AExampleSharedDriveId'   # only for a Shared Drive
```

Channel (profile):

```toml
[profile.channels.mydrive]
type           = 'rbbuild'
remote_service = 'google_mydrive'
repository     = '1AbCdEfGhIjKlMnOpQrStUvWxYz'
root_path      = 'rbbuild/components'
```

Credentials (user configuration):

```toml
[service.google_mydrive]
user          = '1234567890-abc.apps.googleusercontent.com'
credentials   = 'GOCSPX-...'
refresh-token = '1//0g...'
```

| Entry | Where | Comment |
|-------|-------|---------|
| `url` | service | (Optional) Drive API endpoint. Default: `https://www.googleapis.com/` |
| `drive-id` | service | (Optional) ID of the Shared Drive that contains the channel folders. Restricts searches to it |
| `repository` | channel | ID of the root folder (see below) |
| `root_path` | channel | (Optional) Folders below the root folder. They are created on the first upload |
| `user` | user config | OAuth client ID. Required |
| `credentials` | user config | OAuth client secret. Required |
| `refresh-token` | user config | OAuth refresh token. Required |

The channel entry *repository* is the ID of a Drive folder, the last part of the folder URL
`https://drive.google.com/drive/folders/<ID>`. Use `root` for the root of My Drive. For a
Shared Drive, use the ID of the drive itself or of a folder inside it, and set `drive-id`.
With the channel above, a package version is stored in
`<root folder>/rbbuild/components/<name>/<version>/`.

### Obtaining the OAuth credentials

1. In the [Google Cloud console](https://console.cloud.google.com/auth/clients), enable the
   Google Drive API and create an OAuth client of type "Desktop app". This gives the client
   ID and the client secret.
2. Authorize the client once for the scope `https://www.googleapis.com/auth/drive`, for
   example with the [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
   (configured to use your own OAuth client, with *Access type* set to offline). The
   response contains the refresh token.

See [OAuth 2.0 for desktop apps](https://developers.google.com/identity/protocols/oauth2/native-app)
for details. A refresh token is valid until it is revoked. If the consent screen of the
Google Cloud project is in status "Testing", it expires after 7 days.

### Permissions and limitations

* The Google account needs permission to add and delete files in the folders. For
  Shared Drives, deleting requires the role Content manager or Manager.
* Google Drive allows several files with the same name in a folder. rbbuild does not create
  duplicates, but the check for existing files is not atomic.
* Service accounts are not supported.
