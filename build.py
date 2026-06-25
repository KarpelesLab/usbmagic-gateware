#!/usr/bin/env python3
"""Build a usbmagic-gateware bitstream for the Cynthion r1.4 (ECP5 LFE5U-12F).

Runs headless (no board required), so it works in CI inside the Docker image:
Amaranth -> yosys -> nextpnr-ecp5 -> ecppack, writing ``<build-dir>/<name>.bit``.
"""

import argparse

from cynthion.gateware.platform.cynthion_r1_4 import CynthionPlatformRev1D4


def top_from_name(name: str):
    if name == "blinky":
        from blinky import Top

        return Top()
    if name == "pd_bridge":
        from pd_bridge import Top

        return Top()
    if name == "usb_host":
        from usb_host import Top

        return Top()
    raise SystemExit(f"unknown design: {name!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", default="blinky", help="which design to build")
    ap.add_argument("--name", default="usbmagic-blinky", help="output bitstream basename")
    ap.add_argument("--build-dir", default="build", help="output directory")
    args = ap.parse_args()

    platform = CynthionPlatformRev1D4()
    platform.build(
        top_from_name(args.design),
        name=args.name,
        build_dir=args.build_dir,
        do_program=False,
    )
    print(f"bitstream written: {args.build_dir}/{args.name}.bit")


if __name__ == "__main__":
    main()
