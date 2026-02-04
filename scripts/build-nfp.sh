#!/bin/bash

set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo)."
  exit 1
fi

IP_IF="10.111.0.1"
IP_ATTACHED="10.111.0.3"
# IP_IF="192.168.50.1"
# IP_ATTACHED="192.168.50.2"

FW_TREE="$HOME/master/modified-nfp-firmware"
DRV_TREE="$HOME/master/modified-nfp-oot-driver-2019"
ORG_FW_TREE="$HOME/master/org-nfp-firmware"
ORG_DRV_TREE="$HOME/master/nfp-oot-driver-2019"


FW_NAME="nic_AMDA0096-0001_2x10.nffw"
FW_DST_DIR="/lib/firmware/netronome"
NFP_IF="enp2s0np0"
DRV_DST_DIR="/lib/modules/$(uname -r)/updates/"
SKIP_FW=false
SKIP_DRIVER=false
SKIP_CHECK=false
SKIP_BUILD=false
CLEAN=false
DEV=false


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
    --dev)          DEV=true ;;
    --help)         echo " usage (--help --skip-fw --skip-driver --skip-check --skip-build --clean --org --org-fw --org-driver --dev)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--help --skip-fw --skip-driver --skip-check --skip-build --clean --org --org-fw --org-driver --dev)"; exit 1 ;;
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
    modprobe -r nfp 2>/dev/null || true
    if [ "DEV" = true ]; then
      modprobe nfp nfp_dev_cpp=1
    else
      modprobe nfp
    fi
  fi
  update-initramfs -u 2>/dev/null

else
  echo "== Skipping firmware build/install =="
fi

# ============ BUILD DRIVER ==================
if [ "$SKIP_DRIVER" = false ]; then
  echo ""
  echo "============================"
  echo ""
  cd "$DRV_TREE"
  if [ "$SKIP_BUILD" = false ]; then
    echo "== Build driver =="
    if [ "$CLEAN" = true ]; then
        make clean
    fi

    if [ "DEV" = true ]; then
      make nfp_dev_cpp=1
    else
      make
    fi
  fi

  echo "== Install driver =="
  if [ "DEV" = true ]; then
    make nfp_dev_cpp=1 install
  else
    make install
  fi 

  echo "== Reload driver =="
  depmod -a
  modprobe -r nfp 2>/dev/null || true
  if [ "DEV" = true ]; then
    modprobe nfp nfp_dev_cpp=1
  else
    modprobe nfp
  fi
  update-initramfs -u 2>/dev/null

else
  echo "== Skipping driver build/install =="
fi

# ============ HEALTH CHECKS ==================
if [ "$SKIP_CHECK" = false ]; then
  echo ""
  echo "============================"
  echo ""
  echo "== Quick health checks =="
  echo ""
  echo "== nfp module path/version (should show .../extra/... if loaded custom drivers, and dev_cpp enabled) =="
  modinfo -n nfp
  modinfo nfp | egrep -i 'version|o-o-t|filename|cpp' || true
  echo ""
  ls /dev | grep cpp || echo "NB: no dev_cpp interface found!"
  echo ""
  echo "live nfp module srcversion: $(cat /sys/module/nfp/srcversion)"
  echo "disk nfp module srcversion: $(modinfo -F srcversion "$DRV_TREE/src/nfp.ko")"

  echo ""
  echo "==== check firmware logs if loaded and no errors ===="
  logs="$(dmesg)"
  if grep -q 'enp2s0np0 down' <<< "$logs"; then
    printf '%s\n' "$logs" | tac | sed '1,/enp2s0np0 down/!d' | tac
  fi

  echo ""
  echo "==== firmware files present ===="
  ls -l "$FW_DST_DIR" | sed -n '1,200p'

  echo ""
  echo "==== driver bound to interface ===="
  ethtool -i "$NFP_IF" || true

  echo ""
  echo "==== offloads (expect TSO on) ===="
  ethtool -K enp2s0np0 tso on gso on
  ethtool -k "$NFP_IF" | egrep 'tcp-segmentation-offload'

  echo ""
  echo "==== IP address of Netronome interface (should be $IP_IF) ===="
  ip -4 addr show "$NFP_IF"

  echo ""
  echo "==== connectivity over the direct link ===="
  ping -c 3 $IP_ATTACHED || true

  echo ""
  echo "==== active qdisc on interface ===="
  # tc qdisc replace dev enp2s0np0 root cake bandwidth 1gbit besteffort flows no-split-gso || echo "Cake not available"
  tc qdisc replace dev "$NFP_IF" root fq
  tc qdisc show dev "$NFP_IF"

else
  echo "== Skipping health checks =="
fi

if [ "$SKIP_DRIVER" = false ]; then
  echo ""
  echo "NB: to revert to old nfp drivers, run: sudo ./revert-driver.sh"
  echo ""
fi