# sidestore-source

由 GitHub Releases 自动维护的 SideStore / AltStore 应用源。目前收录：

- [Simple Live](https://github.com/June6699/dart_simple_live)
- [PiliPlusX](https://github.com/cnctem/PiliPlusX)
- [PT Mate](https://github.com/JustLookAtNow/pt_mate)

## Source URL

```text
https://raw.githubusercontent.com/lesir831/sidestore-source/main/apps.json
```

## 添加 GitHub 项目

在 `config.json` 的 `apps` 数组中添加一项：

```json
{
  "github": {
    "repository": "owner/repository",
    "assetPattern": "^AppName_.*\\.ipa$",
    "includePrereleases": false,
    "maxVersions": 5,
    "marketingVersionFromTag": false
  },
  "metadata": {
    "name": "App Name",
    "bundleIdentifier": "com.example.app",
    "developerName": "Developer",
    "localizedDescription": "App description",
    "iconURL": "https://example.com/icon.png",
    "category": "utilities",
    "appPermissions": {
      "privacy": {}
    }
  }
}
```

- `repository`：GitHub 的 `owner/repository`。
- `assetPattern`：完整匹配 IPA 文件名的 Python 正则表达式。
- `includePrereleases`：是否收录 GitHub 预发布版本，默认 `false`。
- `maxVersions`：该应用保留的版本数；不填时使用全局默认值 5。
- `marketingVersionFromTag`：将 Release 标签作为展示版本；真实的 `version` 和 `buildVersion` 始终从 IPA 读取。
- `bundleIdentifier`：必须与 IPA 内的 `CFBundleIdentifier` 一致，否则生成会失败。

首次遇到新的 IPA 时，生成器会下载并读取其 `Info.plist`，得到真实 Bundle ID、版本、构建号和最低 iOS 版本，同时计算 SHA-256。已有版本直接复用 `apps.json` 中的元数据，因此定时任务通常只下载新版本。

## 本地更新

```sh
./update_apps.sh
```

临时覆盖每个应用保留的版本数：

```sh
MAX_VERSIONS=3 ./update_apps.sh
```

要求 Python 3.10 或更高版本，不需要第三方 Python 包。GitHub API 令牌可通过 `GH_TOKEN` 或 `GITHUB_TOKEN` 提供；公开仓库在无令牌时也可更新，但会受到较低的 API 速率限制。

GitHub Actions 每小时运行一次；只有 `apps.json` 发生变化时才会提交。
