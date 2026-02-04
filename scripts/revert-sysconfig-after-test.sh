#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 [iface])"
  exit 1
fi

IF="enp1s0np1"


CPU_CORE=3
CPU_GOV="powersave"

GRO_NORMAL_BATCH=8
RPS_SOCK_FLOW_ENTRIES=0

COAL_ADAPT_RX="on"
COAL_ADAPT_TX="on"
COAL_RX_USECS=50
COAL_RX_FRAMES=64
COAL_TX_USECS=50
COAL_TX_FRAMES=64

COMBINED_CHANNELS=2

RPS_CPUS="00"
RPS_FLOW_CNT=0

# irq affinity rxtx-0
# 20 -> bit 5 set -> cpu 5
# 8 -> bit 3 set
IRQ_CPU=5
IRQ_MASK_HEX="20"

# ===== Reverting to defaults ======
echo "Applying resets for IF=$IF..."
echo ""
echo ""

# cpu frequency
cpufreq-set -c "$CPU_CORE" -g "$CPU_GOV"

# sysctls 
sysctl -w "net.core.gro_normal_batch=${GRO_NORMAL_BATCH}" >/dev/null
sysctl -w "net.core.rps_sock_flow_entries=${RPS_SOCK_FLOW_ENTRIES}" >/dev/null


# irqbalance
systemctl enable irqbalance >/dev/null 2>&1 || true
systemctl start  irqbalance >/dev/null 2>&1 || true

# NIC
ethtool -K "$IF" gro on lro off >/dev/null 2>&1 || true

ethtool -C "$IF" adaptive-rx on \
  rx-usecs "$COAL_RX_USECS" rx-frames "$COAL_RX_FRAMES" \
  >/dev/null 2>&1 || true

ethtool -L "$IF" combined "$COMBINED_CHANNELS" >/dev/null 2>&1 || true

# irq affinity for rxtx-0
IRQ="$(awk -v iface="$IF" '$0 ~ iface && /rxtx-0/ { gsub(/:/,"",$1); print $1; exit }' /proc/interrupts || true)"
if [[ -n "${IRQ}" ]]; then
  echo "$IRQ_MASK_HEX" > "/proc/irq/${IRQ}/smp_affinity"
else
  echo "IRQ for $IF rxtx-0 not found (/proc/interrupts)!"
fi

echo ""
echo ""
echo "Reset applied for IF=$IF"