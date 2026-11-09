# sidestore-source

由 GitHub Releases 自动维护的 SideStore / AltStore 应用源。目前收录：

- [Simple Live](https://github.com/June6699/dart_simple_live)
- [Kazumi](https://github.com/Predidit/Kazumi)
- [PiliPlusX](https://github.com/cnctem/PiliPlusX)
- PiliPlusX Legacy（保留旧 Bundle ID 的兼容版本）
- [PiliPlus](https://github.com/bggRGjQaUbCoE/PiliPlus)
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
    "releaseTagPattern": "^v1\\..*$",
    "publishedOnOrAfter": "2026-01-01",
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
- `releaseTagPattern`：可选，完整匹配 Release 标签；适合上游更换 Bundle ID 后隔离不同的应用版本历史。
- `publishedOnOrAfter`：可选，只收录该日期及之后发布的版本，格式为 `YYYY-MM-DD`。
- `includePrereleases`：是否收录 GitHub 预发布版本，默认 `false`。
- `maxVersions`：该应用保留的版本数；不填时使用全局默认值 5。
- `marketingVersionFromTag`：将 Release 标签作为展示版本；真实的 `version` 和 `buildVersion` 始终从 IPA 读取。
- `fallbackRepository` / `fallbackTagPrefix`：可选的 IPA 构建仓库及标签前缀。只在上游同名正式版本缺少 IPA 时使用，版本说明和日期仍来自上游；上游 IPA 始终优先，草稿和预发布构建不参与兜底。
- `bundleIdentifier`：必须与 IPA 内的 `CFBundleIdentifier` 一致，否则生成会失败。

例如 PiliPlusX `v1.1.3.1` 的 IPA 实际版本是 `2.0.6 (5182)`：源中的 `version` / `buildVersion` 必须保持 `2.0.6` / `5182`，并通过 `marketingVersion: 1.1.3.1` 展示项目发布版本。预发布共存包如果使用不同 Bundle ID，必须作为另一应用处理，不能混入稳定版版本列表。

首次遇到新的 IPA 时，生成器会下载并读取其 `Info.plist`，得到真实 Bundle ID、版本、构建号和最低 iOS 版本，同时计算 SHA-256。已有版本直接复用 `apps.json` 中的元数据，因此定时任务通常只下载新版本。

如果 GitHub Releases API 或上游资源短暂不可用，生成器会保留 `apps.json` 中已经验证过的版本，并在 Actions 中给出警告；新配置且尚无缓存的应用仍会失败，避免生成空应用条目。

## 本地更新

```sh
./update_apps.sh
```

临时覆盖每个应用保留的版本数：

```sh
MAX_VERSIONS=3 ./update_apps.sh
```

要求 Python 3.10 或更高版本，不需要第三方 Python 包。GitHub API 令牌可通过 `GH_TOKEN` 或 `GITHUB_TOKEN` 提供；公开仓库在无令牌时也可更新，但会受到较低的 API 速率限制。

GitHub Actions 每小时第 17 分钟计划运行（实际开始时间受 GitHub 调度影响）；只有 `apps.json` 发生变化时才会提交。可用 `gh workflow run update-apps.yml` 立即触发。

## Simple Live 缺少 iOS 发布包时

上游 iOS 工作流是手动触发，默认 `upload_release: false`，因此正式版 Release 可能已经发布，但 IPA 只存在于临时 Actions artifacts 中。应用源生成器本身不编译应用，过去会继续收录旧版 IPA。

现在工作流先检查最新的 `v数字.数字.数字` 正式版（排除 TV、草稿和预发布版本）。上游及本仓库都没有对应 IPA 时，在 macOS runner 上检出上游标签解析出的固定 commit，使用 Flutter 3.41.9 构建未签名 iOS 应用，不注入测试版本后缀。发布前校验 IPA 的 Bundle ID、版本号和构建号必须与配置、上游 `pubspec.yaml` 一致。

兜底构建发布至本仓库的 `simple-live-v版本号` Release，附带 `ios_no_sign.ipa`、对应源码压缩包及 `build-provenance.json`（上游 commit、构建链接、工具版本与 SHA-256）。先上传到草稿，完整上传后才公开；随后同一次工作流生成并提交 `apps.json`。已有可用 IPA 时跳过 macOS 构建。上游后续补发 IPA 时，应用源自动切回上游下载地址。

兜底包是本仓库从上游源码生成的非官方未签名构建，不代表上游官方发布包。该自动化不保证真机运行或具体直播平台可用性。
