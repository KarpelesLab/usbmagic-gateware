# usbmagic-gateware

FPGA gateware for [`usbmagic`](https://github.com/KarpelesLab/usbmagic), targeting
the Great Scott Gadgets **Cynthion** (ECP5 `LFE5U-12F`, board rev 1.4).

The end goal is a **USB 2.0 host controller** (so `usbmagic` can drive a device
under test directly — see usbmagic's `docs/ARCHITECTURE.md`). This repo currently
contains the Phase-0 **bring-up blinky** that proves the build + flash pipeline.

## Layout

- `blinky.py` — the bring-up design (blinks the six user LEDs).
- `build.py` — headless bitstream build (`<build-dir>/<name>.bit`).
- `Dockerfile` — reproducible toolchain: oss-cad-suite (yosys + nextpnr-ecp5 +
  prjtrellis/ecppack) + Amaranth/LUNA/Cynthion.
- `.github/workflows/build.yml` — CI: builds the bitstream in the image, uploads
  it as an artifact, and attaches it to GitHub releases on tags.

## Build

With Docker (reproducible, no host toolchain needed):

```sh
docker build -t usbmagic-gateware .
docker run --rm -v "$PWD:/work" -w /work usbmagic-gateware python3 build.py
# -> build/usbmagic-blinky.bit
```

Or natively, if you have oss-cad-suite + the Python deps:

```sh
pip install -r requirements.txt
python3 build.py
```

## Flashing

The bitstream is flashed to the board by `usbmagic` itself (Rust, over the Apollo
USB interface) — see `usbmagic`'s `firmware/` and `usbmagic flash`. The released
`.bit` is vendored into the `usbmagic` repo via Git LFS.

## License

BSD-3-Clause (see [`LICENSE`](LICENSE)). Derived from / depends on Cynthion and
LUNA (BSD-3-Clause, © 2022–2024 Great Scott Gadgets); their copyright is retained.
