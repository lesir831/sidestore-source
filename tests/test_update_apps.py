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


def make_release(payload, *, tag="v1.2.3", body="Release notes"):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-08T00:00:00Z",
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
