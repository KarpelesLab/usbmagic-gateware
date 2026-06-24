#!/usr/bin/env python3
#
# usbmagic-gateware — PD bridge.
#
# Exposes the Cynthion's TARGET-C Type-C controller (FUSB302B, on the FPGA's
# I2C bus) to the host as simple GPIO bits over a JTAG register interface. The
# host (usbmagic, in Rust) bit-bangs I2C by toggling SCL/SDA through these
# registers and reads SDA back — keeping all I2C/PD logic host-side, where it is
# easy to iterate without re-flashing gateware.
#
# Register access uses LUNA's JTAGRegisterInterface (CSRs over the ECP5 user JTAG
# register), the same mechanism Cynthion's selftest uses; the host reaches it via
# Apollo over JTAG.
#
# SPDX-License-Identifier: BSD-3-Clause
# Builds on Cynthion/LUNA (BSD-3-Clause, (c) 2020-2024 Great Scott Gadgets).

from amaranth import Cat, Elaboratable, Module, Signal

from luna.gateware.architecture.car import LunaECP5DomainGenerator
from luna.gateware.interface.jtag import JTAGRegisterInterface

# Register map (read/written by the host over JTAG).
REG_ID = 1            # read-only identity, to confirm the bridge is live
REG_GPIO_OUT = 2      # TARGET-C: bit0 = SCL level (push-pull), bit1 = SDA drive-low
REG_GPIO_IN = 3       # TARGET-C: bit0 = SDA line level, bit1 = FUSB302B INT#
REG_SCRATCH = 4       # read/write scratch, to exercise the register path
REG_AUX_GPIO_OUT = 5  # AUX: bit0 = SCL level, bit1 = SDA drive-low
REG_AUX_GPIO_IN = 6   # AUX: bit0 = SDA line level, bit1 = FUSB302B INT#

# "uPDB" — usbmagic PD bridge.
ID_MAGIC = 0x7550_4442


class Top(Elaboratable):
    def elaborate(self, platform):
        m = Module()

        m.submodules.clocking = LunaECP5DomainGenerator(
            clock_frequencies={"fast": 60, "sync": 60, "usb": 60}
        )

        regs = JTAGRegisterInterface(default_read_value=0xDEADBEEF)
        m.submodules.registers = regs

        regs.add_read_only_register(REG_ID, read=ID_MAGIC)
        regs.add_register(REG_SCRATCH, size=32, name="scratch")

        # TARGET-C Type-C controller (FUSB302B) I2C, as open-drain-ish GPIO.
        tc = platform.request("target_type_c")

        # bit0 = SCL level (master always drives SCL push-pull),
        # bit1 = SDA drive-low (1 -> pull SDA low; 0 -> release, external pull-up).
        # Idle I2C is SCL high, SDA released -> init = 0b01.
        gpio_out = regs.add_register(REG_GPIO_OUT, size=2, name="gpio_out", init=0b01)
        m.d.comb += [
            tc.scl.o.eq(gpio_out[0]),
            tc.sda.o.eq(0),
            tc.sda.oe.eq(gpio_out[1]),
        ]

        # Live inputs: SDA line and the FUSB302B interrupt.
        regs.add_sfr(REG_GPIO_IN, read=Cat(tc.sda.i, tc.int.i))

        # AUX Type-C controller (FUSB302B), same open-drain-GPIO scheme.
        aux = platform.request("aux_type_c")
        aux_out = regs.add_register(REG_AUX_GPIO_OUT, size=2, name="aux_gpio_out", init=0b01)
        m.d.comb += [
            aux.scl.o.eq(aux_out[0]),
            aux.sda.o.eq(0),
            aux.sda.oe.eq(aux_out[1]),
        ]
        regs.add_sfr(REG_AUX_GPIO_IN, read=Cat(aux.sda.i, aux.int.i))

        # Heartbeat so it's visually distinct from blinky: LED0 blinks, LED5
        # mirrors the SDA line, the rest are off.
        counter = Signal(25)
        m.d.sync += counter.eq(counter + 1)
        led0 = platform.request("led", 0, dir="o").o
        led5 = platform.request("led", 5, dir="o").o
        m.d.comb += [
            led0.eq(counter[-1]),
            led5.eq(tc.sda.i),
        ]

        return m


if __name__ == "__main__":
    from luna import top_level_cli

    top_level_cli(Top)
