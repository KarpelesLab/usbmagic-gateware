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
# Per-port I2C master: a command register (write-triggered) and a status register.
REG_TC_CMD = 2        # TARGET-C I2C command  (write)  + VBUS-switch control
REG_TC_STATUS = 3     # TARGET-C I2C status   (read)   + VBUS-switch read-back
REG_AUX_CMD = 5       # AUX I2C command       (write)
REG_AUX_STATUS = 6    # AUX I2C status        (read)

# Command register bits (REG_TC_CMD / REG_AUX_CMD).
CMD_START = 1 << 0
CMD_STOP = 1 << 1
CMD_WRITE = 1 << 2
CMD_READ = 1 << 3
CMD_ACK = 1 << 4      # for READ: 1 = send ACK (continue), 0 = NACK (last byte)
CMD_SET_VBUS = 1 << 5  # (TARGET-C only) latch cmd[31:24] as the VBUS switches
# bits[15:8] = byte to transmit for WRITE; bits[31:24] = VBUS switches (with CMD_SET_VBUS).
#
# Only registers created inside the per-port loop below reliably capture the
# written word in this LUNA/JTAGRegisterInterface version, so VBUS-switch control
# rides on the TARGET-C command register rather than a standalone register.

# VBUS switch bits (cmd[31:24] when CMD_SET_VBUS is set; mirrored in status[23:16]).
VBUS_TARGET_C = 1 << 0       # connect TARGET-C VBUS <-> TARGET-A rail
VBUS_CONTROL = 1 << 1        # connect CONTROL VBUS <-> rail (host 5V; do not mix with a supply)
VBUS_AUX = 1 << 2            # connect AUX VBUS <-> rail
VBUS_TARGET_A_DISCHARGE = 1 << 3
VBUS_AUX_IN = 1 << 4         # let the AUX port's VBUS into the board (input shutoff release)
VBUS_CONTROL_IN = 1 << 5     # let the CONTROL port's VBUS into the board

# Status register layout: bit0 busy, bit1 ack_o (0 = slave ACKed), bits[15:8] data_o,
# bits[23:16] = latched VBUS switches (TARGET-C status only).

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

        # VBUS load-switch state. Each port's VBUS connects to the shared
        # TARGET-A rail (per the analyzer gateware's model); init 0 keeps every
        # switch open. The host bridges e.g. AUX -> TARGET-C to charge a device.
        switches = Signal(8, init=0, name="vbus_switches")

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

            # add_register latches the new value on the cycle AFTER write_strobe,
            # so delay the strobe one cycle to line it up with the updated `cmd`.
            cmd_loaded = Signal(name=f"{name}_cmd_loaded")
            m.d.sync += cmd_loaded.eq(cmd_strobe)

            # A register write pulses the selected op for one cycle (the
            # initiator ignores strobes while busy; the host polls busy first).
            m.d.comb += [
                i2c.start.eq(cmd_loaded & cmd[0]),
                i2c.stop.eq(cmd_loaded & cmd[1]),
                i2c.write.eq(cmd_loaded & cmd[2]),
                i2c.read.eq(cmd_loaded & cmd[3]),
                i2c.ack_i.eq(cmd[4]),
                i2c.data_i.eq(cmd[8:16]),
            ]

            # VBUS switch control piggybacks on the TARGET-C command register —
            # the one register path proven to capture the written word. (Registers
            # created OUTSIDE this loop get their write strobe but never the data
            # in this LUNA/JTAGRegisterInterface version: confirmed on hardware via
            # debug LEDs — strobe fires, word_received never arrives. The in-loop
            # cmd registers do capture it, as the working I2C proves.) So: cmd
            # bit5 = "this write sets the VBUS switches", switch bits in cmd[24:32].
            # I2C ops keep bit5 clear and a VBUS write keeps bits0-4 clear, so the
            # two never disturb each other. The latched state is mirrored back into
            # the TARGET-C status register's bits[23:16] for read-back.
            if name == "tc":
                with m.If(cmd_loaded & cmd[5]):
                    m.d.sync += switches.eq(cmd[24:32])
                status = Cat(i2c.busy, i2c.ack_o, Const(0, 6), i2c.data_o, switches)
            else:
                status = Cat(i2c.busy, i2c.ack_o, Const(0, 6), i2c.data_o)
            regs.add_sfr(status_addr, read=status)

        m.d.comb += [
            platform.request("target_c_vbus_en").o.eq(switches[0]),
            platform.request("control_vbus_en").o.eq(switches[1]),
            platform.request("aux_vbus_en").o.eq(switches[2]),
            platform.request("target_a_discharge").o.eq(switches[3]),
            # Input-shutoff releases (PinsN in the platform: .o=1 lets VBUS in).
            platform.request("aux_vbus_in_en").o.eq(switches[4]),
            platform.request("control_vbus_in_en").o.eq(switches[5]),
        ]

        # LED0 heartbeat; LED1-5 mirror the latched VBUS switch state:
        # LED1=target_c, LED2=aux, LED3=aux_in, LED4=control, LED5=control_in.
        counter = Signal(25)
        m.d.sync += counter.eq(counter + 1)
        m.d.comb += platform.request("led", 0, dir="o").o.eq(counter[-1])
        m.d.comb += platform.request("led", 1, dir="o").o.eq(switches[0])
        m.d.comb += platform.request("led", 2, dir="o").o.eq(switches[2])
        m.d.comb += platform.request("led", 3, dir="o").o.eq(switches[4])
        m.d.comb += platform.request("led", 4, dir="o").o.eq(switches[1])
        m.d.comb += platform.request("led", 5, dir="o").o.eq(switches[5])

        return m


if __name__ == "__main__":
    from luna import top_level_cli

    top_level_cli(Top)
