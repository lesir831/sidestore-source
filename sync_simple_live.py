#!/usr/bin/env python3
"""Plan and verify unsigned builds for Simple Live releases missing an IPA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from update_apps import SourceError, choose_releases, inspect_ipa, load_json, validate_config


def gh_api(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def plan_build(
    github: dict[str, Any],
    upstream: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> dict[str, str]:
    """Only build the newest stable mobile release, never TV or test releases."""
    releases = sorted(
        (
            release for release in upstream
            if not release.get("draft")
            and not release.get("prerelease")
            and re.fullmatch(github["releaseTagPattern"], release.get("tag_name", ""))
        ),
        key=lambda release: release.get("published_at") or "",
        reverse=True,
    )
    if not releases:
        raise SourceError("No stable Simple Live mobile release found")
    latest = releases[0]
    tag = latest["tag_name"]
    # These values become checkout refs, filenames, and release tags in Actions.
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None:
        raise SourceError(f"Unexpected Simple Live release tag: {tag}")
    available = choose_releases(
        [latest], github["assetPattern"], False, 1,
        fallback_releases=fallback,
        fallback_tag_prefix=github["fallbackTagPrefix"],
    )
    return {
        "build_needed": "false" if available else "true",
        "repository": github["repository"],
        "tag": tag,
        "release_tag": f"{github['fallbackTagPrefix']}{tag}",
    }


def verify_ipa(path: Path, bundle_id: str, version: str, build_version: str) -> dict[str, str]:
    with path.open("rb") as file:
        info = inspect_ipa(file)
    for key, expected in (
        ("bundleIdentifier", bundle_id),
        ("version", version),
        ("buildVersion", build_version),
    ):
        if info[key] != expected:
            raise SourceError(f"Built IPA {key} is {info[key]}, expected {expected}")
    with path.open("rb") as file:
        digest = hashlib.sha256()
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return {**info, "sha256": digest.hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "verify"])
    parser.add_argument("--ipa", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_json(Path(__file__).with_name("config.json"))
    validate_config(config)
    app = next(app for app in config["apps"] if app["metadata"]["bundleIdentifier"] == "com.xycz.simple-live")
    github = app["github"]

    if args.command == "plan":
        upstream = gh_api(f"repos/{github['repository']}/releases?per_page=100")
        fallback = gh_api(f"repos/{github['fallbackRepository']}/releases?per_page=100")
        plan = plan_build(github, upstream, fallback)
        if plan["build_needed"] == "true":
            import base64

            # Resolve tags (including annotated tags) to an immutable commit.
            commit = gh_api(f"repos/{github['repository']}/commits/{quote(plan['tag'], safe='')}")
            plan["sha"] = commit["sha"]
            pubspec = gh_api(
                f"repos/{github['repository']}/contents/simple_live_app/pubspec.yaml?ref={plan['sha']}"
            )
            text = base64.b64decode(pubspec["content"]).decode()
            match = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)\+([0-9]+)\s*$", text, re.MULTILINE)
            if match is None or f"v{match[1]}" != plan["tag"]:
                raise SourceError("Release tag and pubspec version do not match")
            plan["version"], plan["build_version"] = match.groups()
        print(json.dumps(plan, indent=2))
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as file:
                for key, value in plan.items():
                    file.write(f"{key}={value}\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as file:
                status = "IPA missing; building from the release commit" if plan["build_needed"] == "true" else "IPA already available"
                file.write(f"Simple Live **{plan['tag']}**: {status}.\n")
    else:
        if args.ipa is None or args.output is None:
            parser.error("verify requires --ipa and --output")
        info = verify_ipa(
            args.ipa, app["metadata"]["bundleIdentifier"],
            os.environ["EXPECTED_VERSION"], os.environ["EXPECTED_BUILD_VERSION"],
        )
        info.update({
            "upstreamRepository": github["repository"],
            "upstreamTag": os.environ["UPSTREAM_TAG"],
            "upstreamCommit": os.environ["UPSTREAM_SHA"],
            "flutterVersion": os.environ["FLUTTER_VERSION"],
            "buildURL": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        })
        args.output.write_text(json.dumps(info, indent=2) + "\n")
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
