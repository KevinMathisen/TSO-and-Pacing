#!/bin/bash

set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo)."
  exit 1
fi

VER=$(uname -r)
DRV_MOD_DIR="/lib/modules/$VER/updates/drivers/net/ethernet/netronome/nfp"

rm -f /lib/modules/$(uname -r)/updates/nfp.ko
depmod -a
modprobe -r nfp 2>/dev/null || true
modprobe -v nfp

echo ""
echo "-- nfp module path/version (should NOT show .../updates/...) --"
modinfo -n nfp

echo ""
echo "-- check firmware logs if loaded and no errors --"
if dmesg | grep -q 'enp2s0np0 down'; then
  dmesg | tac | sed '1,/enp2s0np0 down/!d' | tac
fi