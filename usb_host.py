#!/usr/bin/env python3
#
# usbmagic-gateware — USB 2.0 host (full-speed), phase 1: PHY bring-up.
#
# Drives the Cynthion TARGET port's ULPI PHY (target_phy) as a USB **host** in
# full-speed mode and detects a device connecting. This first bitstream is
# deliberately LED-only — no register read-back path yet — so we can prove the
# PHY comes up and sees the device by eye before building the transaction engine.
#
# VBUS for the device is routed from the CONTROL port (the operator host's 5 V)
# to TARGET-C through the existing switch matrix (no PD/I2C needed).
#
# LEDs:
#   0  sync-domain heartbeat   — the FPGA core is alive
#   5  usb-domain heartbeat    — the ULPI 60 MHz clock is running (PHY clocking)
#   1  vbus_valid              — the PHY sees VBUS on the target port
#   2  connected               — a full-speed device is attached (J state, debounced)
#   3  line_state[0] (D+)
#   4  line_state[1] (D-)
#
# SPDX-License-Identifier: BSD-3-Clause
# Builds on Cynthion/LUNA (BSD-3-Clause, (c) 2020-2024 Great Scott Gadgets).

from amaranth import Elaboratable, Module, Signal

from luna.gateware.architecture.car import LunaECP5DomainGenerator
from luna.gateware.interface.ulpi import UTMITranslator

# ULPI line_state (for the configured speed): 00=SE0, 01=J, 10=K, 11=SE1.
# A full-speed device idles in J once its D+ pull-up is seen by the host.
LINE_STATE_J = 0b01

# Debounce ~1 ms at 60 MHz before declaring "connected".
CONNECT_DEBOUNCE = 60_000


class Top(Elaboratable):
    def elaborate(self, platform):
        m = Module()

        # Clock domains: default LUNA generator gives sync=120 MHz (internal) and
        # usb=60 MHz sourced from the ULPI clock once the PHY is up.
        m.submodules.clocking = LunaECP5DomainGenerator()

        # ULPI -> UTMI on the TARGET port PHY. handle_clocking wires the ULPI
        # clock into the `usb` domain.
        ulpi = platform.request("target_phy")
        m.submodules.utmi = utmi = UTMITranslator(ulpi=ulpi)

        # --- Full-speed HOST mode -------------------------------------------
        # Present host pull-downs, full-speed termination + transceiver, normal
        # signalling. (We are the host; the device presents the D+ pull-up.)
        m.d.comb += [
            utmi.xcvr_select.eq(0b01),  # full speed
            utmi.term_select.eq(1),     # FS termination
            utmi.op_mode.eq(0b00),      # normal
            utmi.dp_pulldown.eq(1),     # host 15k pull-downs
            utmi.dm_pulldown.eq(1),
        ]

        # --- VBUS: route CONTROL (host 5 V) -> TARGET-C ---------------------
        # (PinsN: .o=1 lets the port's VBUS into the board.)
        m.d.comb += [
            platform.request("control_vbus_in_en").o.eq(1),
            platform.request("control_vbus_en").o.eq(1),
            platform.request("target_c_vbus_en").o.eq(1),
        ]

        # --- Connect detection (usb domain) ---------------------------------
        connected = Signal()
        debounce = Signal(range(CONNECT_DEBOUNCE + 1))
        with m.If(utmi.line_state == LINE_STATE_J):
            with m.If(debounce == CONNECT_DEBOUNCE):
                m.d.usb += connected.eq(1)
            with m.Else():
                m.d.usb += debounce.eq(debounce + 1)
        with m.Else():
            m.d.usb += [debounce.eq(0), connected.eq(0)]

        # --- Heartbeats: prove each clock domain is alive -------------------
        sync_hb = Signal(25)
        m.d.sync += sync_hb.eq(sync_hb + 1)
        usb_hb = Signal(25)
        m.d.usb += usb_hb.eq(usb_hb + 1)

        # --- LEDs -----------------------------------------------------------
        m.d.comb += [
            platform.request("led", 0, dir="o").o.eq(sync_hb[-1]),
            platform.request("led", 1, dir="o").o.eq(utmi.vbus_valid),
            platform.request("led", 2, dir="o").o.eq(connected),
            platform.request("led", 3, dir="o").o.eq(utmi.line_state[0]),
            platform.request("led", 4, dir="o").o.eq(utmi.line_state[1]),
            platform.request("led", 5, dir="o").o.eq(usb_hb[-1]),
        ]

        return m


if __name__ == "__main__":
    from luna import top_level_cli

    top_level_cli(Top)
