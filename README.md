# Simple Live AltStore Source

Automatically maintained AltStore source for [Simple Live](https://github.com/June6699/dart_simple_live) (com.xycz.simple-live).

- `source.json` — app metadata (fixed fields)
- `update_apps.sh` — fetches the latest releases from `June6699/dart_simple_live` and regenerates `apps.json` (keeps the newest 5 versions)
- `.github/workflows/update-apps.yml` — scheduled (hourly) + manual update of `apps.json`

## AltStore source URL

```
https://raw.githubusercontent.com/lesir831/simple-live-altstore/main/apps.json
```

## Manual update

```sh
./update_apps.sh
```

Set `MAX_VERSIONS` to change how many versions are kept (default 5).

## Requirements

- `jq`, `python3`
- `gh` CLI (falls back to unauthenticated curl if not available)
