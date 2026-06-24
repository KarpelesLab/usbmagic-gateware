#!/usr/bin/env python3
#
# usbmagic-gateware — bring-up "blinky" for the Cynthion ECP5.
#
# This is the Phase-0 pipeline proof: a trivial design that blinks the six user
# LEDs, used to validate that the toolchain (Amaranth -> yosys -> nextpnr-ecp5 ->
# ecppack) and the flashing path produce a working bitstream on real hardware,
# before the real USB host controller gateware is written.
#
# Adapted from the Great Scott Gadgets Cynthion blinky tutorial
# (cynthion/python/examples/tutorials/gateware-blinky.py),
# Copyright (c) 2024 Great Scott Gadgets <info@greatscottgadgets.com>,
# SPDX-License-Identifier: BSD-3-Clause.

from amaranth import Cat, Elaboratable, Module, Signal


class Top(Elaboratable):
    """Blink the six user LEDs at ~1 Hz off the 60 MHz ULPI clock."""

    def elaborate(self, platform):
        m = Module()

        leds = Cat(platform.request("led", n).o for n in range(0, 6))

        half_freq = int(60e6 // 2)
        timer = Signal(range(half_freq + 1))

        with m.If(timer == half_freq - 1):
            m.d.sync += leds.eq(~leds)
            m.d.sync += timer.eq(0)
        with m.Else():
            m.d.sync += timer.eq(timer + 1)

        return m


if __name__ == "__main__":
    # Convenience: build + (optionally) program when run directly with a board
    # attached. CI uses build.py instead.
    from luna import top_level_cli

    top_level_cli(Top)
