#!/bin/bash

set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo)."
  exit 1
fi

FW_TREE="$HOME/master/modified-nfp-firmware"
DRV_TREE="$HOME/master/modified-nfp-driver"
ORG_FW_TREE="$HOME/master/org-nfp-firmware"
ORG_DRV_TREE="$HOME/master/org-nfp-driver"
FW_NAME="nic_AMDA0096-0001_2x10.nffw"
FW_DST_DIR="/lib/firmware/netronome"
NFP_IF="enp2s0np0"
DRV_DST_DIR="/lib/modules/$(uname -r)/updates/"
SKIP_FW=false
SKIP_DRIVER=false
SKIP_CHECK=false
SKIP_BUILD=false
CLEAN=false

for arg in "$@"; do
  case "$arg" in
    --skip-fw)      SKIP_FW=true ;;
    --skip-driver)  SKIP_DRIVER=true ;;
    --skip-check)   SKIP_CHECK=true ;;
    --skip-build)   SKIP_BUILD=true ;;
    --clean)        CLEAN=true ;;
    --org)          FW_TREE="$ORG_FW_TREE"; DRV_TREE="$ORG_DRV_TREE"; SKIP_BUILD=true ;;
    --org-fw)       FW_TREE="$ORG_FW_TREE"; SKIP_BUILD=true ;;
    --org-driver)   DRV_TREE="$ORG_DRV_TREE"; SKIP_BUILD=true ;;
    --help)         echo " usage (--help --skip-fw --skip-driver --skip-check --clean --org --org-fw --org-driver)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--help --skip-fw --skip-driver --skip-check --skip-build --clean --org --org-fw --org-driver)"; exit 1 ;;
  esac
done

[ -d "$FW_TREE" ] || { echo "Missing FW_TREE: $FW_TREE"; exit 1; }
[ -d "$DRV_TREE" ] || { echo "Missing DRV_TREE: $DRV_TREE"; exit 1; }

# ============ BUILD FIRMWARE ================
if [ "$SKIP_FW" = false ]; then
  cd "$FW_TREE"
  if [ "$SKIP_BUILD" = false ]; then
    echo "== Build firmware =="
    if [ "$CLEAN" = true ]; then
        make clean
    fi
    make "nic/$FW_NAME"

    # Remove previously loaded firmware
    rm -rf "$FW_DST_DIR"/*
  fi

  echo "== Install firmware =="
  cp -r "$FW_TREE/firmware/nffw"/* "$FW_DST_DIR"/
  cp "$FW_DST_DIR"/nic/* "$FW_DST_DIR"/

  # Reload nfp kernel module with new firmware here if we skip driver updates
  if [ "$SKIP_DRIVER" = true ]; then
    echo "== Reload driver =="
    depmod -a
    rmmod nfp 2>/dev/null || true
    modprobe nfp nfp_dev_cpp=1
  fi
  update-initramfs -u 2>/dev/null

else
  echo "== Skipping firmware build/install =="
fi

# ============ BUILD DRIVER ==================
if [ "$SKIP_DRIVER" = false ]; then
  cd "$DRV_TREE"
  if [ "$SKIP_BUILD" = false ]; then
    echo "== Build driver =="
    
    make -C /lib/modules/$(uname -r)/build M=$PWD clean
    make -C /lib/modules/$(uname -r)/build M=$PWD modules
  fi

  echo "== Reload driver =="
  # place nfp.ko in updates/ so it is used instead of host drivers
  install -D -m 0644 ./nfp.ko "$DRV_DST_DIR/nfp.ko"

  depmod -a
  modprobe -r nfp 2>/dev/null || true
  modprobe -v nfp nfp_dev_cpp=1
  update-initramfs -u 2>/dev/null

else
  echo "== Skipping driver build/install =="
fi

# ============ HEALTH CHECKS ==================
if [ "$SKIP_CHECK" = false ]; then
  echo "== Quick health checks =="
  echo ""
  echo "-- nfp module path/version (should show .../updates/... if loaded custom drivers) --"
  modinfo -n nfp
  modinfo nfp | egrep -i 'version|o-o-t|filename' || true
  echo "live nfp module srcversion: $(cat /sys/module/nfp/srcversion)"
  echo "disk nfp module srcversion: $(modinfo -F srcversion /lib/modules/$(uname -r)/updates/nfp.ko)"

  echo ""
  echo "-- check firmware logs if loaded and no errors --"
  logs="$(dmesg)"
  if grep -q 'enp2s0np0 down' <<< "$logs"; then
    printf '%s\n' "$logs" | tac | sed '1,/enp2s0np0 down/!d' | tac
  fi

  echo ""
  echo "-- firmware files present --"
  ls -l "$FW_DST_DIR" | sed -n '1,200p'

  echo ""
  echo "-- driver bound to interface --"
  ethtool -i "$NFP_IF" || true

  echo ""
  echo "-- offloads (expect TSO on) --"
  ethtool -K enp2s0np0 tso on gso on
  ethtool -k "$NFP_IF" | egrep 'tcp-segmentation-offload'

  echo ""
  echo "-- IP address of Netronome interface (should be 10.111.0.1/24) --"
  ip -4 addr show "$NFP_IF"

  echo ""
  echo "-- connectivity over the direct link --"
  ping -c 3 10.111.0.3 || true

  echo ""
  echo "-- internet connectivity (default gateway should be via motherboard NIC) --"
  ping -c 3 8.8.8.8 || true

  echo ""
  echo "-- active qdisc on interface (should be cake with bandwidth 1Gbit and no-split-gso)"
  sudo tc qdisc replace dev enp2s0np0 root cake bandwidth 1gbit besteffort flows no-split-gso
  tc qdisc show dev "$NFP_IF"

else
  echo "== Skipping health checks =="
fi

if [ "$SKIP_DRIVER" = false ]; then
  echo ""
  echo "NB: to revert to old nfp drivers, run: sudo ./revert-driver.sh"
  echo ""
fi