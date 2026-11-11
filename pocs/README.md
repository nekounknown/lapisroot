# PoC drop-in directory

`lapisroot hunt` never ships an exploit. It only executes a PoC that you place
here yourself, for a catalogued CVE that the device actually matches.

## Layout

```
pocs/
  CVE-2025-38352/
    manifest.json
    poc
```

`manifest.json`:

```json
{
  "command": ["./poc", "--target", "android"],
  "timeout": 60,
  "reversible": false,
  "expected": "uid=0"
}
```

- `command` (required): argv list, executed with `cwd` set to the CVE directory.
- `timeout` (optional): seconds, default 60.
- `reversible` (optional): whether the PoC can be undone without a reboot.
- `expected` (optional): a string you expect in the output, for your own review.

A bare `run.sh` in the CVE directory is also accepted.

## Rules

- Only PoCs you have reviewed and trust. The harness will not fetch one.
- `hunt --execute` refuses to run non-interactively without `--yes`.
- Nothing is written to the device by the harness itself; the PoC does whatever
  it does, so treat it as hostile code and run it only on hardware you own.
