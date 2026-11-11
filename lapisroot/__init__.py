"""lapisroot - temporary root toolkit for the Redmi Note 15 Pro 5G.

The device is codenamed ``lapis`` and is built on the MediaTek MT6878
(Dimensity 7400-Ultra).  It ships with an ``init_boot`` partition, which is
the partition that must be patched on Android 13+ launch devices.
"""

from __future__ import annotations

__version__ = "0.1.0"

#: Device codename reported by ``ro.product.device`` / ``fastboot getvar product``.
CODENAME = "lapis"

#: MediaTek platform id reported by ``ro.board.platform``.
PLATFORM = "mt6878"

#: Marketing name, used only for human-readable output.
MARKETING_NAME = "Redmi Note 15 Pro 5G"

#: SoC marketing name.
SOC_NAME = "MediaTek Dimensity 7400-Ultra"

#: Partition that holds the generic ramdisk on this device.
BOOT_PARTITION = "init_boot"

#: Device uses A/B (seamless) slots.
A_B_SLOTS = True
