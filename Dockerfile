# Reproducible build environment for usbmagic-gateware (Cynthion ECP5 LFE5U-12F).
#
# Bundles the open-source ECP5 flow (yosys + nextpnr-ecp5 + prjtrellis/ecppack
# from oss-cad-suite) and the Amaranth/LUNA/Cynthion Python stack, so a bitstream
# build is fully reproducible locally and in CI:
#
#   docker build -t usbmagic-gateware .
#   docker run --rm -v "$PWD:/work" -w /work usbmagic-gateware python3 build.py
#
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        git curl ca-certificates xz-utils libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Open-source ECP5 toolchain (yosys + nextpnr-ecp5 + prjtrellis/ecppack) ---
# Grabs the latest oss-cad-suite linux-x64 release. For full reproducibility,
# replace `releases/latest` with a specific tag, e.g.
#   .../releases/download/2025-06-01/oss-cad-suite-linux-x64-20250601.tgz
RUN set -eux; \
    url="$(curl -fsSL https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest \
          | grep -oE '"browser_download_url": *"[^"]*linux-x64[^"]*\.tgz"' \
          | head -n1 | cut -d'"' -f4)"; \
    echo "oss-cad-suite: $url"; \
    curl -fsSL -o /tmp/oss-cad-suite.tgz "$url"; \
    mkdir -p /opt; tar -xzf /tmp/oss-cad-suite.tgz -C /opt; \
    rm /tmp/oss-cad-suite.tgz

# --- Amaranth + LUNA + Cynthion platform (Python venv) ---
RUN python3 -m venv /opt/venv
# venv first (its python), then the toolchain binaries on PATH.
ENV PATH="/opt/venv/bin:/opt/oss-cad-suite/bin:${PATH}"
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /work
CMD ["python3", "build.py"]
