# lapisroot — Temporary root for the Redmi Note 15 Pro 5G (KernelSU LKM and Shizuku LPE)

Target device: **Redmi Note 15 Pro 5G** (codename `lapis` / MediaTek **MT6878** Dimensity 7400-Ultra)

> **Relevant CVE: [CVE-2026-98260](https://nvd.nist.gov/vuln/detail/CVE-2026-98260)** — Linux `exec` POSIX CPU timer use-after-free; affects 5.7–6.1.190, fixed in 6.1.191. The reference `lapis` kernel (6.1.138) is in range, and `hunt` flags it.

A Linux toolkit with two routes to temporary root. The `lapisroot` CLI injects **KernelSU's LKM** (Loadable Kernel Module) into the `init_boot` partition; it does not replace the kernel itself, and `stop` writes the original `init_boot` back byte-for-byte. The `apk/` route runs a local payload through Shizuku and does not touch `init_boot` at all.

- **`apk/` (Shizuku LPE)** — **no bootloader unlock required.** No fastboot, no `init_boot` write, no reboot.
- **`lapisroot` CLI (KernelSU LKM)** — requires an unlocked bootloader, because it flashes `init_boot` via fastboot.

The rest of this document describes the KernelSU route unless stated otherwise.

## CVE coverage at a glance

The bundled catalog tracks seven public Android/MediaTek privilege-escalation issues, and `hunt` evaluates each one against the device build. **No exploits are shipped**: a PoC runs only if you place one under `pocs/<CVE>/`.

| CVE | Title | Component | Status on the reference `lapis` build (kernel 6.1.138) |
|---|---|---|---|
| CVE-2026-98260 | POSIX CPU timer use-after-free in exec | kernel | **`vulnerable`** (6.1.138 < 6.1.191) |
| CVE-2022-0847 | Dirty Pipe | kernel | `not-applicable` (kernel newer) |
| CVE-2023-0386 | OverlayFS privilege escalation | kernel | `not-applicable` (kernel newer) |
| CVE-2024-31317 | Zygote command injection | framework | `patched` (SDK newer) |
| CVE-2024-53104 | USB video class out-of-bounds write | kernel | `patched` (patch date) |
| CVE-2025-38352 | POSIX CPU timer use-after-free | kernel | `patched` (patch date) |
| CVE-2025-21479 | Qualcomm GPU privilege escalation | gpu | `not-applicable` (Qualcomm only) |

> **CVE-2026-98260 applies to the reference `lapis` kernel (6.1.138).** Affects 5.7–6.1.190, fixed in 6.1.191. CVSS 7.8 HIGH. NVD: <https://nvd.nist.gov/vuln/detail/CVE-2026-98260>

```bash
python3 -m lapisroot hunt
```

The catalog is curated and non-exhaustive; verify every entry against the vendor bulletin. Schema, evaluation rules, and how to add entries: [`docs/cves.md`](docs/cves.md).

---

## What you should know first (important)

1. **An unlocked bootloader is required for the KernelSU `init_boot` route.**
   That route is not an exploit that bypasses locking: it flashes `init_boot` via fastboot, so it does nothing on a locked bootloader. **Bootloader unlock is not required for the `apk/` Shizuku route.**

2. **A full RAM boot via `fastboot boot` is not possible.**
   `lapis` uses the Android 13+ layout (the generic ramdisk lives in `init_boot`), so `init_boot.img` does not contain the kernel. The "vanishes on reboot" RAM boot approach is unavailable; instead, `init_boot` is rewritten and restored by `stop`.

3. **Root persists across reboots until you run `stop`.**
   "Temporary" means "can be reliably reverted with `stop`". KernelSU Manager's "Temporary uninstall" can disable root until the next reboot.

4. **The stock `init_boot.img` from the same build is mandatory.**
   Flashing an image from a different build will make the device unbootable due to AVB / anti-rollback. Always extract it from the fastboot ROM that matches the current build.

---

## No bootloader unlock: the Shizuku APK route

The `apk/` project gets a shell on the device without touching `init_boot` or fastboot:

1. Enable USB debugging and start Shizuku (via `adb` or wireless debugging).
2. Install the APK from the release: `adb install -r lapisroot.apk`.
3. Launch it: `adb shell am start -n com.lapisroot.exploit/.MainActivity --ez auto true`.
4. Grant the Shizuku permission prompt.

The APK runs `libexploit.so shell` through Shizuku's shell and prints the result in the app log and `last_run.txt`. This route **does not require a bootloader unlock**, does not flash anything, and does not reboot. What it can do is limited to the payload and the device build; it does not provide KernelSU's persistent `su`.

---

## How it works

KernelSU's `ksud boot-patch` performs the following on the `init_boot.img` ramdisk:

- backs up the original `/init` to `/init.real`
- installs `ksuinit` as `/init`
- adds `kernelsu.ko` (an LKM matching the KMI)
- adds `ksu_config`

At boot, `ksuinit` loads `kernelsu.ko`, and KernelSU's `su` becomes available. The kernel (`boot.img`) is untouched, which avoids compatibility issues with MediaTek vendor modules.

---

## Requirements

- Linux PC (x86_64 or aarch64)
- `adb` / `fastboot` (Android Platform Tools)
- Python 3.10 or newer
- A `lapis` with an unlocked bootloader for the KernelSU route (not required for the `apk/` Shizuku route)
- Shizuku running on the device for the `apk/` route
- The fastboot ROM (`.tgz`) or `init_boot.img` matching the current build
- The device's KMI (auto-detected from `uname -r` when connected via `adb`)

The `lapis` kernel is Xiaomi's MediaTek BSP (`lapis-v-oss`) and is most likely `android14-6.1`. If auto-detection fails, pass `--kmi android14-6.1`.

---

## Usage

### 1. Check the device and KMI

```bash
python3 -m lapisroot detect
```

`kmi: android14-6.1` means it's OK. If it says `unauthorized`, approve "Allow USB debugging?" on the device.

### 2. Review the plan

```bash
python3 -m lapisroot plan --stock /path/to/init_boot.img
```

`route: ready` means you can proceed. `route: locked` means the bootloader must be unlocked first.

### 3. Start temporary root

```bash
python3 -m lapisroot start \
  --stock /path/to/init_boot.img \
  --kmi android14-6.1 \
  --allow-shell
```

- `--stock` accepts a single `init_boot.img`, a directory of an extracted fastboot ROM, or the ROM's `.tgz` / `.zip` (only `init_boot.img` is extracted from archives).
- With `--allow-shell`, `adb shell su` works without the Manager's approval dialog. Without it, grant access in KernelSU Manager on the device.
- On first run, the tool also downloads the KernelSU Manager APK and installs it via `adb install` (disable with `--no-manager`).
- A confirmation prompt appears before execution. Use `--yes` only for automation.

### 4. Check status

```bash
python3 -m lapisroot status
```

### 5. Revert (end temporary root)

```bash
python3 -m lapisroot stop
```

Writes the stock `init_boot` recorded in the journal back and reboots. Root is gone.

---

## Troubleshooting

### Bootloop

Boot into fastboot (hold Power + Volume Down) and run `lapisroot stop`. If that still fails, flash the stock image directly.

```bash
fastboot flash init_boot /path/to/init_boot.img
fastboot reboot
```

### "KMI mismatch" / boots but root does not work

Use `--lkm` to point at a `kernelsu.ko` that matches the kernel. KernelSU's official LKM can fail to load unless the KMI generation (the number after `android14-6.1`) matches exactly. KernelSU Next / SukiSU Ultra LKMs can also be used via `--variant` and `--lkm`.

```bash
python3 -m lapisroot start --stock init_boot.img --kmi android14-6.1 \
  --variant KernelSU-Next --lkm /path/to/aarch64_android14-6.1_kernelsu.ko
```

### Bootloader is locked

1. Apply for unlock in Xiaomi Community (Global region)
2. Wait 72 hours to 30 days for the binding period
3. Unlock with Mi Unlock (wipes data)

Devices from the China region are not eligible for the official unlock. Commercial ADB unlock services exist, but this tool is not involved with them.

### Diagnose MediaTek BROM / preloader

```bash
python3 -m lapisroot brom probe
```

`mtkclient` is required. Power off the device, then connect USB while holding Volume Up (or Down) to enter preloader/BROM mode.

**This command is read-only.** mtkclient's DA support for MT6878 is still incomplete, and writing is not possible when Xiaomi's preloader requires DAA/SLA. Writing to the boot partition through BROM with a locked bootloader would make the device unbootable due to AVB, so this tool intentionally does not implement BROM writes.

---

## Automated vulnerability hunting

```bash
python3 -m lapisroot hunt
python3 -m lapisroot hunt --execute --yes
```

`hunt` collects patch level, kernel, platform, SELinux, and build tags from the device and matches them against the bundled CVE catalog (`lapisroot/data/android_lpe_catalog.json`).

- If no known public LPE applies to the build, it says so explicitly and exits. It never fabricates an exploit.
- **No PoCs are bundled.** Only PoCs you place yourself at `pocs/<CVE>/manifest.json` (or `run.sh`) are executed by `--execute`. See `pocs/README.md` for the format.
- `--execute` does not run without interactive confirmation. Use `--yes` only for automation.
- `--json` writes an execution report to `state-dir/reports/`.
- The catalog can be replaced with `--catalog`. It is not an exhaustive database, so always cross-check it against vendor bulletins.

See [`docs/cves.md`](docs/cves.md) for the catalog schema, the bundled entries, and the evaluation rules.

A practical order for hunting known LPEs with a locked bootloader is `hunt` -> if nothing applies, `brom probe` -> if that still fails, unlock the bootloader.

---

## Limitations and disclaimer

- This project does not bypass bootloader unlock, disable AVB, or spoof Play Integrity.
- Device data loss, bricking, and warranty loss are the user's responsibility.
- Always use a stock image that matches the current build.
- After a Xiaomi HyperOS update, `init_boot` changes, so you must re-extract the stock image and run `start` again.
- The `apk/` Shizuku route grants only what the payload provides; it does not give KernelSU's persistent `su`.

---

## Layout

```
lapisroot/
  adb.py        adb wrapper
  fastboot.py   fastboot wrapper
  device.py     device detection, BL state, KMI detection, routing
  firmware.py   init_boot discovery/validation and partial archive extraction
  kernelsu.py   ksud fetch, KMI detection, boot-patch execution
  brom.py       read-only mtkclient diagnostics
  workspace.py  journal and stock image backup
  temp.py       start / stop / status orchestration
  cli.py        command line
tests/          unit tests
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

`ksud boot-patch` itself can be exercised against a synthetic `init_boot.img` created with `mkbootimg`.

```bash
python3 - <<'PY'
from pathlib import Path
from lapisroot import kernelsu
bundle = kernelsu.KsuBundle(version="local", ksud=Path("/path/to/ksud"))
print(kernelsu.patch(bundle, Path("init_boot.img"), Path("out"), kmi="android14-6.1"))
PY
```
