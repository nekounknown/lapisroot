# CVE catalog and `lapisroot hunt`

`lapisroot hunt` matches the device against a curated, non-exhaustive catalog of public Android/MediaTek privilege-escalation issues. The bundled data lives in [`lapisroot/data/android_lpe_catalog.json`](../lapisroot/data/android_lpe_catalog.json).

This project does not ship exploits. `hunt` only executes a PoC that you place under `pocs/<CVE>/` yourself; see [`pocs/README.md`](../pocs/README.md).

## How evaluation works

For each entry, in order:

1. **Platform filter** — if `platform` is set and the device reports a different `ro.board.platform` or codename, the entry is `not-applicable`.
2. **SDK ceiling** — if `max_sdk` is set and the device SDK is higher, the entry is `patched` (the issue does not affect newer SDK levels).
3. **Security patch date** — if `fixed_security_patch` is set and the device's `ro.build.version.security_patch` is on or after it, the entry is `patched`. A missing or unparseable date on either side yields `unknown`.
4. **Kernel range** — if `min_kernel` / `max_kernel` is set, the `X.Y.Z` prefix of the device kernel is compared. Outside the range means `not-applicable`; an unparseable kernel yields `unknown`.
5. Otherwise the entry is `vulnerable`.

Limits: the version comparison ignores vendor backports and the rest of the kernel suffix, and the patch date is a coarse signal. Always cross-check the vendor bulletin.

## Catalog format

```json
{
  "schema": 1,
  "updated": "YYYY-MM-DD",
  "disclaimer": "...",
  "entries": []
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | CVE identifier; also the PoC directory name under `pocs/` |
| `title` | yes | Short human-readable title |
| `component` | yes | `kernel`, `framework`, `gpu`, ... |
| `impact` | no | Defaults to `root` |
| `platform` | no | Restrict to a platform or codename (for example `qualcomm`) |
| `fixed_security_patch` | no* | ISO date of the vendor fix |
| `max_sdk` | no* | Highest affected SDK level |
| `min_kernel` | no* | Lowest affected kernel `X.Y.Z` |
| `max_kernel` | no* | Highest affected kernel `X.Y.Z` |
| `notes` | no | Free-form context |

\* At least one of `fixed_security_patch`, `max_sdk`, `min_kernel`, or `max_kernel` is required. An entry without a constraint is rejected when the catalog loads.

## Bundled entries

| CVE | Title | Component | Platform | Fixed patch | Kernel range | Max SDK |
|---|---|---|---|---|---|---|
| CVE-2022-0847 | Dirty Pipe | kernel | - | 2022-03-01 | <= 5.16.10 | - |
| CVE-2023-0386 | OverlayFS privilege escalation | kernel | - | 2023-03-01 | <= 6.1.8 | - |
| CVE-2024-31317 | Zygote command injection | framework | - | 2024-06-01 | - | 33 |
| CVE-2024-53104 | USB video class out-of-bounds write | kernel | - | 2024-12-01 | - | - |
| CVE-2025-38352 | POSIX CPU timer use-after-free | kernel | - | 2025-07-01 | - | - |
| CVE-2025-21479 | Qualcomm GPU privilege escalation | gpu | qualcomm | 2025-06-01 | - | - |

The catalog is curated and non-exhaustive. The bundled list deliberately contains no candidate for the current `lapis` build (SDK 36, patch 2026-09); `hunt` reports that explicitly.

## Adding or replacing entries

- Use the vendor bulletin's patch date, not the upstream kernel release date.
- Keep the `X.Y.Z` kernel form; a suffix such as `-android14-11-gabc` is ignored.
- Set `platform` only when the issue is genuinely SoC-specific.
- Verify the entry against the bulletin before committing; the disclaimer does not replace verification.
- Replace the whole file with `--catalog /path/to/catalog.json` when testing a local catalog.

## Status values

| Status | Meaning |
|---|---|
| `vulnerable` | All constraints say the build is affected |
| `patched` | The patch date or SDK ceiling rules the entry out |
| `not-applicable` | The platform or kernel range rules the entry out |
| `unknown` | A required device fact (patch date or kernel) is missing |
