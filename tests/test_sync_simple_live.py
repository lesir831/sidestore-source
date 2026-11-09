import copy
import tempfile
import unittest
from pathlib import Path

import sync_simple_live
from test_update_apps import make_ipa, make_release
from update_apps import SourceError


GITHUB = {
    "repository": "upstream/app",
    "assetPattern": r"^Example-ios\.ipa$",
    "releaseTagPattern": r"^v[0-9]+\.[0-9]+\.[0-9]+$",
    "fallbackTagPrefix": "simple-live-",
}


class BuildPlanningTests(unittest.TestCase):
    def setUp(self):
        self.latest = make_release(b"", tag="v1.13.3", published_at="2026-11-08T13:17:59Z")
        self.latest["assets"] = []
        self.previous = make_release(b"", tag="v1.13.2", published_at="2026-10-20T10:21:52Z")

    def test_builds_latest_mobile_release_missing_ipa_despite_old_ipa(self):
        tv = make_release(b"", tag="tv_v1.8.3", published_at="2026-11-09T00:00:00Z")
        test = make_release(b"", tag="v1.14.0", published_at="2026-11-09T00:00:00Z")
        test["prerelease"] = True
        plan = sync_simple_live.plan_build(GITHUB, [self.previous, tv, test, self.latest], [])
        self.assertEqual(plan["build_needed"], "true")
        self.assertEqual(plan["tag"], "v1.13.3")
        self.assertEqual(plan["release_tag"], "simple-live-v1.13.3")

    def test_does_not_build_if_upstream_has_ipa(self):
        self.latest["assets"] = self.previous["assets"]
        plan = sync_simple_live.plan_build(GITHUB, [self.latest, self.previous], [])
        self.assertEqual(plan["build_needed"], "false")

    def test_does_not_rebuild_published_fallback(self):
        fallback = make_release(b"", tag="simple-live-v1.13.3")
        plan = sync_simple_live.plan_build(GITHUB, [self.latest], [fallback])
        self.assertEqual(plan["build_needed"], "false")

    def test_retries_partial_draft_or_missing_ipa(self):
        fallback = make_release(b"", tag="simple-live-v1.13.3")
        draft = copy.deepcopy(fallback)
        draft["draft"] = True
        fallback["assets"] = []
        for release in [draft, fallback]:
            with self.subTest(release=release):
                plan = sync_simple_live.plan_build(GITHUB, [self.latest], [release])
                self.assertEqual(plan["build_needed"], "true")

    def test_no_stable_mobile_release_is_an_error(self):
        with self.assertRaisesRegex(SourceError, "No stable"):
            sync_simple_live.plan_build(GITHUB, [], [])

    def test_rejects_wrong_ipa_identity_or_version_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            ipa = Path(directory) / "app.ipa"
            ipa.write_bytes(make_ipa(version="1.13.3", build_version="11303"))
            info = sync_simple_live.verify_ipa(ipa, "com.example.app", "1.13.3", "11303")
            self.assertEqual(len(info["sha256"]), 64)
            for bundle, version, build in [
                ("com.other.app", "1.13.3", "11303"),
                ("com.example.app", "1.13.2", "11303"),
                ("com.example.app", "1.13.3", "11302"),
            ]:
                with self.subTest(bundle=bundle, version=version, build=build):
                    with self.assertRaises(SourceError):
                        sync_simple_live.verify_ipa(ipa, bundle, version, build)


if __name__ == "__main__":
    unittest.main()
