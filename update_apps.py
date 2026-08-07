#!/usr/bin/env python3
"""Generate an AltStore/SideStore source from configured GitHub releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, BinaryIO


API_ROOT = "https://api.github.com"
USER_AGENT = "sidestore-source-generator/1"
REQUIRED_CACHE_KEYS = {
    "version",
    "buildVersion",
    "downloadURL",
    "size",
    "minOSVersion",
    "sha256",
}


class SourceError(RuntimeError):
    """Raised when configuration or an upstream release is invalid."""


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def _request(self, url: str, *, accept: str) -> urllib.request.Request:
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(url, headers=headers)

    def releases(self, repository: str) -> list[dict[str, Any]]:
        url = f"{API_ROOT}/repos/{repository}/releases?per_page=100"
        request = self._request(url, accept="application/vnd.github+json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SourceError(f"Failed to fetch releases for {repository}: {error}") from error
        if not isinstance(payload, list):
            raise SourceError(f"Unexpected releases response for {repository}")
        return payload

    def download(self, url: str) -> tuple[BinaryIO, str]:
        request = self._request(url, accept="application/octet-stream")
        output = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
        except (urllib.error.URLError, TimeoutError) as error:
            output.close()
            raise SourceError(f"Failed to download {url}: {error}") from error
        output.seek(0)
        return output, digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise SourceError(f"Failed to read {path}: {error}") from error
    if not isinstance(value, dict):
        raise SourceError(f"{path} must contain a JSON object")
    return value


def existing_version_cache(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for app in source.get("apps", []):
        for version in app.get("versions", []):
            url = version.get("downloadURL")
            if (
                isinstance(url, str)
                and REQUIRED_CACHE_KEYS <= version.keys()
                and all(version.get(key) not in (None, "") for key in REQUIRED_CACHE_KEYS)
            ):
                cache[url] = {
                    **version,
                    "_bundleIdentifier": app.get("bundleIdentifier"),
                }
    return cache


def normalize_tag(tag: str) -> str:
    return re.sub(r"^v\.?", "", tag, count=1, flags=re.IGNORECASE)


def inspect_ipa(file: BinaryIO) -> dict[str, str]:
    try:
        with zipfile.ZipFile(file) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name)
            ]
            if len(candidates) != 1:
                raise SourceError(
                    f"IPA must contain exactly one top-level app Info.plist; found {len(candidates)}"
                )
            plist = plistlib.loads(archive.read(candidates[0]))
    except (zipfile.BadZipFile, KeyError, plistlib.InvalidFileException) as error:
        raise SourceError(f"Invalid IPA: {error}") from error

    values = {
        "bundleIdentifier": plist.get("CFBundleIdentifier"),
        "version": plist.get("CFBundleShortVersionString"),
        "buildVersion": plist.get("CFBundleVersion"),
        "minOSVersion": plist.get("MinimumOSVersion"),
    }
    missing = [key for key, value in values.items() if value in (None, "")]
    if missing:
        raise SourceError(f"IPA Info.plist is missing: {', '.join(missing)}")
    return {key: str(value) for key, value in values.items()}


def validate_config(config: dict[str, Any]) -> None:
    if config.get("schemaVersion") != 1:
        raise SourceError("config.json schemaVersion must be 1")
    if not isinstance(config.get("source"), dict):
        raise SourceError("config.json must contain a source object")
    apps = config.get("apps")
    if not isinstance(apps, list) or not apps:
        raise SourceError("config.json must contain at least one app")

    bundle_ids: set[str] = set()
    for index, app in enumerate(apps):
        github = app.get("github")
        metadata = app.get("metadata")
        if not isinstance(github, dict) or not isinstance(metadata, dict):
            raise SourceError(f"apps[{index}] must contain github and metadata objects")
        repository = github.get("repository")
        pattern = github.get("assetPattern")
        bundle_id = metadata.get("bundleIdentifier")
        if not all(isinstance(value, str) and value for value in (repository, pattern, bundle_id)):
            raise SourceError(
                f"apps[{index}] requires github.repository, github.assetPattern, "
                "and metadata.bundleIdentifier"
            )
        try:
            re.compile(pattern)
        except re.error as error:
            raise SourceError(f"Invalid assetPattern for {repository}: {error}") from error
        if bundle_id in bundle_ids:
            raise SourceError(f"Duplicate bundle identifier: {bundle_id}")
        bundle_ids.add(bundle_id)


def choose_releases(
    releases: list[dict[str, Any]], asset_pattern: str, include_prereleases: bool, limit: int
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pattern = re.compile(asset_pattern)
    chosen: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for release in releases:
        if release.get("draft") or (release.get("prerelease") and not include_prereleases):
            continue
        matches = [
            asset
            for asset in release.get("assets", [])
            if isinstance(asset.get("name"), str) and pattern.fullmatch(asset["name"])
        ]
        if not matches:
            continue
        if len(matches) > 1:
            names = ", ".join(asset["name"] for asset in matches)
            raise SourceError(f"Release {release.get('tag_name')} matched multiple IPA assets: {names}")
        chosen.append((release, matches[0]))
        if len(chosen) == limit:
            break
    return chosen


def version_from_release(
    release: dict[str, Any],
    asset: dict[str, Any],
    expected_bundle_id: str,
    marketing_version_from_tag: bool,
    cache: dict[str, dict[str, Any]],
    client: GitHubClient,
) -> tuple[dict[str, Any], bool]:
    url = asset.get("browser_download_url")
    size = asset.get("size")
    if not isinstance(url, str) or not isinstance(size, int):
        raise SourceError(f"Release {release.get('tag_name')} has invalid asset metadata")

    cached = cache.get(url)
    downloaded = False
    if (
        cached is not None
        and cached.get("size") == size
        and cached.get("_bundleIdentifier") == expected_bundle_id
    ):
        ipa = {
            "version": str(cached["version"]),
            "buildVersion": str(cached["buildVersion"]),
            "minOSVersion": str(cached["minOSVersion"]),
        }
        sha256 = cached.get("sha256")
    else:
        file, sha256 = client.download(url)
        downloaded = True
        try:
            ipa = inspect_ipa(file)
        finally:
            file.close()
        if ipa["bundleIdentifier"] != expected_bundle_id:
            raise SourceError(
                f"{asset.get('name')} bundle identifier is {ipa['bundleIdentifier']}, "
                f"expected {expected_bundle_id}"
            )

    published_at = release.get("published_at") or release.get("created_at")
    if not isinstance(published_at, str) or len(published_at) < 10:
        raise SourceError(f"Release {release.get('tag_name')} has no valid publication date")
    version = {
        "version": ipa["version"],
        "buildVersion": ipa["buildVersion"],
        "date": published_at[:10],
        "localizedDescription": release.get("body") or "",
        "downloadURL": url,
        "size": size,
        "minOSVersion": ipa["minOSVersion"],
    }
    if isinstance(sha256, str) and sha256:
        version["sha256"] = sha256
    if marketing_version_from_tag:
        tag = release.get("tag_name")
        if isinstance(tag, str) and tag:
            version["marketingVersion"] = normalize_tag(tag)
    return version, downloaded


def build_source(
    config: dict[str, Any],
    existing: dict[str, Any],
    client: GitHubClient,
    max_versions_override: int | None = None,
) -> tuple[dict[str, Any], int]:
    validate_config(config)
    defaults = config.get("defaults", {})
    default_limit = defaults.get("maxVersions", 5)
    if not isinstance(default_limit, int) or default_limit < 1:
        raise SourceError("defaults.maxVersions must be a positive integer")
    cache = existing_version_cache(existing)
    output = dict(config["source"])
    output_apps: list[dict[str, Any]] = []
    download_count = 0

    for app_config in config["apps"]:
        github = app_config["github"]
        metadata = app_config["metadata"]
        repository = github["repository"]
        limit = max_versions_override or github.get("maxVersions", default_limit)
        if not isinstance(limit, int) or limit < 1:
            raise SourceError(f"maxVersions for {repository} must be a positive integer")
        include_prereleases = github.get(
            "includePrereleases", defaults.get("includePrereleases", False)
        )
        if not isinstance(include_prereleases, bool):
            raise SourceError(f"includePrereleases for {repository} must be a boolean")

        releases = choose_releases(
            client.releases(repository), github["assetPattern"], include_prereleases, limit
        )
        if not releases:
            raise SourceError(f"No matching IPA releases found for {repository}")

        app = dict(metadata)
        versions: list[dict[str, Any]] = []
        for release, asset in releases:
            version, downloaded = version_from_release(
                release,
                asset,
                metadata["bundleIdentifier"],
                github.get("marketingVersionFromTag", False),
                cache,
                client,
            )
            versions.append(version)
            download_count += int(downloaded)
        app["versions"] = versions
        output_apps.append(app)
        print(
            f"{metadata.get('name', repository)}: {len(versions)} versions, "
            f"latest {versions[0]['version']} ({versions[0]['buildVersion']})",
            file=sys.stderr,
        )

    output["apps"] = output_apps
    output.setdefault("news", [])
    return output, download_count


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temporary_path = Path(file.name)
    try:
        temporary_path.replace(path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=script_dir / "config.json")
    parser.add_argument("--output", type=Path, default=script_dir / "apps.json")
    parser.add_argument("--max-versions", type=positive_integer)
    args = parser.parse_args()

    try:
        env_limit = os.environ.get("MAX_VERSIONS")
        max_versions = args.max_versions
        if max_versions is None and env_limit is not None:
            max_versions = positive_integer(env_limit)
        config = load_json(args.config)
        existing = (
            load_json(args.output)
            if args.output.exists() and args.output.stat().st_size > 0
            else {}
        )
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        source, downloads = build_source(config, existing, GitHubClient(token), max_versions)
        write_json_atomic(args.output, source)
    except (SourceError, OSError, argparse.ArgumentTypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Updated {args.output} ({len(source['apps'])} apps, {downloads} new IPA downloads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
