#!/usr/bin/env python3
#
# usbmagic-gateware — PD bridge.
#
# Exposes the Cynthion's TARGET-C and AUX Type-C controllers (FUSB302B, on the
# FPGA's I2C buses) to the host via a hardware I2C master (LUNA's I2CInitiator),
# reached over a JTAG register interface. The host issues byte-level I2C ops
# (start / write / read / stop) by writing a command register and reading a
# status register — far faster than host-side bit-banging, which matters for
# draining the FUSB302B RX FIFO during a live PD exchange.
#
# Register access uses LUNA's JTAGRegisterInterface (CSRs over the ECP5 user JTAG
# register), the same mechanism Cynthion's selftest uses; the host reaches it via
# Apollo over JTAG.
#
# SPDX-License-Identifier: BSD-3-Clause
# Builds on Cynthion/LUNA (BSD-3-Clause, (c) 2020-2024 Great Scott Gadgets).

from amaranth import Cat, Const, Elaboratable, Module, Signal

from luna.gateware.architecture.car import LunaECP5DomainGenerator
from luna.gateware.interface.jtag import JTAGRegisterInterface
from luna.gateware.interface.i2c import I2CInitiator

# Register map (read/written by the host over JTAG).
REG_ID = 1            # read-only identity
REG_SCRATCH = 4       # read/write scratch, to exercise the register path
# Per-port I2C master: a command register (write-triggered) and a status register.
REG_TC_CMD = 2        # TARGET-C I2C command  (write)
REG_TC_STATUS = 3     # TARGET-C I2C status   (read)
REG_AUX_CMD = 5       # AUX I2C command       (write)
REG_AUX_STATUS = 6    # AUX I2C status        (read)

# Command register bits.
CMD_START = 1 << 0
CMD_STOP = 1 << 1
CMD_WRITE = 1 << 2
CMD_READ = 1 << 3
CMD_ACK = 1 << 4      # for READ: 1 = send ACK (continue), 0 = NACK (last byte)
# bits[15:8] = byte to transmit for WRITE.

# Status register layout: bit0 busy, bit1 ack_o (0 = slave ACKed), bits[15:8] data_o.

# "uPDB" — usbmagic PD bridge.
ID_MAGIC = 0x7550_4442

# ~100 kHz I2C at 60 MHz (period in system-clock cycles).
I2C_PERIOD_CYC = 600


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

        # A hardware I2C master per Type-C controller.
        for name, resource, cmd_addr, status_addr in (
            ("tc", "target_type_c", REG_TC_CMD, REG_TC_STATUS),
            ("aux", "aux_type_c", REG_AUX_CMD, REG_AUX_STATUS),
        ):
            pads = platform.request(resource)
            i2c = I2CInitiator(pads=pads, period_cyc=I2C_PERIOD_CYC, clk_stretch=False)
            m.submodules[f"i2c_{name}"] = i2c

            cmd_strobe = Signal(name=f"{name}_cmd_strobe")
            cmd = regs.add_register(
                cmd_addr, size=32, name=f"{name}_cmd", write_strobe=cmd_strobe
            )

            # A register write pulses the selected op for one cycle (the
            # initiator ignores strobes while busy; the host polls busy first).
            m.d.comb += [
                i2c.start.eq(cmd_strobe & cmd[0]),
                i2c.stop.eq(cmd_strobe & cmd[1]),
                i2c.write.eq(cmd_strobe & cmd[2]),
                i2c.read.eq(cmd_strobe & cmd[3]),
                i2c.ack_i.eq(cmd[4]),
                i2c.data_i.eq(cmd[8:16]),
            ]
            regs.add_sfr(
                status_addr,
                read=Cat(i2c.busy, i2c.ack_o, Const(0, 6), i2c.data_o),
            )

        # Heartbeat so it's visually distinct: LED0 blinks.
        counter = Signal(25)
        m.d.sync += counter.eq(counter + 1)
        led0 = platform.request("led", 0, dir="o").o
        m.d.comb += led0.eq(counter[-1])

        return m


if __name__ == "__main__":
    from luna import top_level_cli

    top_level_cli(Top)
