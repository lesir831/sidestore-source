import copy
import hashlib
import io
import plistlib
import unittest
import zipfile

import update_apps


def make_ipa(
    *,
    bundle_identifier="com.example.app",
    version="2.3.4",
    build_version="234",
    minimum_os="14.0",
):
    output = io.BytesIO()
    info = {
        "CFBundleIdentifier": bundle_identifier,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build_version,
        "MinimumOSVersion": minimum_os,
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Payload/Example.app/Info.plist", plistlib.dumps(info))
    return output.getvalue()


def make_config(bundle_identifier="com.example.app"):
    return {
        "schemaVersion": 1,
        "source": {
            "name": "sidestore-source",
            "identifier": "com.example.source",
            "apps": [],
            "news": [],
        },
        "defaults": {"maxVersions": 5, "includePrereleases": False},
        "apps": [
            {
                "github": {
                    "repository": "owner/repository",
                    "assetPattern": r"^Example.*\.ipa$",
                    "marketingVersionFromTag": True,
                },
                "metadata": {
                    "name": "Example",
                    "bundleIdentifier": bundle_identifier,
                    "developerName": "Developer",
                    "localizedDescription": "Description",
                    "iconURL": "https://example.com/icon.png",
                },
            }
        ],
    }


def make_release(
    payload, *, tag="v1.2.3", body="Release notes", published_at="2026-08-08T00:00:00Z"
):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": published_at,
        "body": body,
        "assets": [
            {
                "name": "Example-ios.ipa",
                "size": len(payload),
                "browser_download_url": "https://example.com/Example-ios.ipa",
            }
        ],
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.downloads = []
        self.release = make_release(payload)

    def releases(self, repository):
        self.repository = repository
        return [self.release]

    def download(self, url):
        self.downloads.append(url)
        return io.BytesIO(self.payload), hashlib.sha256(self.payload).hexdigest()


class FailingReleaseClient(FakeClient):
    def releases(self, repository):
        raise update_apps.SourceError("GitHub Releases API is temporarily unavailable")


class SourceGeneratorTests(unittest.TestCase):
    def test_reads_versions_from_ipa_and_uses_tag_only_for_marketing(self):
        payload = make_ipa()
        client = FakeClient(payload)

        source, download_count = update_apps.build_source(make_config(), {}, client)

        version = source["apps"][0]["versions"][0]
        self.assertEqual(client.repository, "owner/repository")
        self.assertEqual(download_count, 1)
        self.assertEqual(version["version"], "2.3.4")
        self.assertEqual(version["buildVersion"], "234")
        self.assertEqual(version["marketingVersion"], "1.2.3")
        self.assertEqual(version["minOSVersion"], "14.0")
        self.assertEqual(version["sha256"], hashlib.sha256(payload).hexdigest())

    def test_reuses_verified_cache_and_refreshes_release_notes(self):
        payload = make_ipa()
        client = FakeClient(payload)
        url = client.release["assets"][0]["browser_download_url"]
        existing = {
            "apps": [
                {
                    "bundleIdentifier": "com.example.app",
                    "versions": [
                        {
                            "version": "2.3.4",
                            "buildVersion": "234",
                            "date": "2026-08-01",
                            "localizedDescription": "Old notes",
                            "downloadURL": url,
                            "size": len(payload),
                            "minOSVersion": "14.0",
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    ],
                }
            ]
        }

        source, download_count = update_apps.build_source(make_config(), existing, client)

        version = source["apps"][0]["versions"][0]
        self.assertEqual(download_count, 0)
        self.assertEqual(client.downloads, [])
        self.assertEqual(version["localizedDescription"], "Release notes")
        self.assertEqual(version["date"], "2026-08-08")

    def test_keeps_verified_versions_when_release_assets_temporarily_disappear(self):
        payload = make_ipa()
        client = FakeClient(payload)
        existing, _ = update_apps.build_source(make_config(), {}, client)
        client.release["assets"] = []
        client.downloads.clear()

        source, download_count = update_apps.build_source(make_config(), existing, client)

        self.assertEqual(download_count, 0)
        self.assertEqual(client.downloads, [])
        self.assertEqual(source["apps"][0]["versions"], existing["apps"][0]["versions"])

    def test_keeps_verified_versions_when_release_request_fails(self):
        payload = make_ipa()
        existing, _ = update_apps.build_source(make_config(), {}, FakeClient(payload))
        client = FailingReleaseClient(payload)

        source, download_count = update_apps.build_source(make_config(), existing, client)

        self.assertEqual(download_count, 0)
        self.assertEqual(client.downloads, [])
        self.assertEqual(source["apps"][0]["versions"], existing["apps"][0]["versions"])

    def test_does_not_hide_ambiguous_release_assets_with_cached_versions(self):
        payload = make_ipa()
        client = FakeClient(payload)
        existing, _ = update_apps.build_source(make_config(), {}, client)
        client.release["assets"].append(dict(client.release["assets"][0]))

        with self.assertRaisesRegex(update_apps.SourceError, "matched multiple IPA assets"):
            update_apps.build_source(make_config(), existing, client)

    def test_filters_releases_by_tag_pattern(self):
        payload = make_ipa()
        legacy = make_release(payload, tag="v1.1.3.1")
        current = make_release(payload, tag="v1.1.5.0")

        releases = update_apps.choose_releases(
            [current, legacy], r"^Example.*\.ipa$", False, 5, r"^v1\.1\.[0-3](?:\..*)?$"
        )

        self.assertEqual([release["tag_name"] for release, _ in releases], ["v1.1.3.1"])

    def test_filters_releases_by_minimum_publication_date(self):
        payload = make_ipa()
        current = make_release(payload, tag="v2.0.0", published_at="2026-07-09T00:00:00Z")
        legacy = make_release(payload, tag="v1.0.0", published_at="2026-07-08T23:59:59Z")

        releases = update_apps.choose_releases(
            [current, legacy], r"^Example.*\.ipa$", False, 5, None, "2026-07-09"
        )

        self.assertEqual([release["tag_name"] for release, _ in releases], ["v2.0.0"])

    def test_splits_bundle_id_lineages_from_one_release_snapshot(self):
        current_payload = make_ipa(
            bundle_identifier="com.example.current", version="2.0", build_version="200"
        )
        legacy_payload = make_ipa(
            bundle_identifier="com.example.legacy", version="1.0", build_version="100"
        )
        current_release = make_release(current_payload, tag="v2.0.0")
        legacy_release = make_release(legacy_payload, tag="v1.0.0")
        current_url = "https://example.com/current.ipa"
        legacy_url = "https://example.com/legacy.ipa"
        current_release["assets"][0]["browser_download_url"] = current_url
        legacy_release["assets"][0]["browser_download_url"] = legacy_url

        class SplitClient:
            def __init__(self):
                self.release_requests = 0

            def releases(self, repository):
                self.release_requests += 1
                return [current_release, legacy_release]

            def download(self, url):
                payload = {current_url: current_payload, legacy_url: legacy_payload}[url]
                return io.BytesIO(payload), hashlib.sha256(payload).hexdigest()

        config = make_config("com.example.current")
        config["apps"][0]["github"]["releaseTagPattern"] = r"^v2\..*$"
        legacy_config = copy.deepcopy(config["apps"][0])
        legacy_config["github"]["releaseTagPattern"] = r"^v1\..*$"
        legacy_config["metadata"]["name"] = "Example Legacy"
        legacy_config["metadata"]["bundleIdentifier"] = "com.example.legacy"
        config["apps"].append(legacy_config)
        client = SplitClient()

        source, download_count = update_apps.build_source(config, {}, client)

        self.assertEqual(client.release_requests, 1)
        self.assertEqual(download_count, 2)
        self.assertEqual(
            [app["bundleIdentifier"] for app in source["apps"]],
            ["com.example.current", "com.example.legacy"],
        )

    def test_rejects_invalid_release_tag_pattern(self):
        config = make_config()
        config["apps"][0]["github"]["releaseTagPattern"] = "["

        with self.assertRaisesRegex(update_apps.SourceError, "Invalid releaseTagPattern"):
            update_apps.validate_config(config)

    def test_rejects_invalid_minimum_publication_date(self):
        config = make_config()
        config["apps"][0]["github"]["publishedOnOrAfter"] = "2026-02-30"

        with self.assertRaisesRegex(update_apps.SourceError, "publishedOnOrAfter"):
            update_apps.validate_config(config)

    def test_rejects_an_unexpected_bundle_identifier(self):
        payload = make_ipa(bundle_identifier="com.example.actual")
        client = FakeClient(payload)

        with self.assertRaisesRegex(update_apps.SourceError, "bundle identifier"):
            update_apps.build_source(make_config("com.example.expected"), {}, client)

    def test_ignores_prereleases_by_default(self):
        payload = make_ipa()
        client = FakeClient(payload)
        client.release["prerelease"] = True

        with self.assertRaisesRegex(update_apps.SourceError, "No matching IPA releases"):
            update_apps.build_source(make_config(), {}, client)


if __name__ == "__main__":
    unittest.main()
