#!/bin/bash

echo "BUILDING FIRMWARE"
# Clean and build firmware
cd /home/atleia/Documents/master/agilio/modified-nic-firmware/nic-firmware;

make clean;

make nic/nic_AMDA0096-0001_2x10.nffw;

# Remove previously loaded firmware
cd /lib/firmware/netronome;
rm -r /lib/firmware/netronome/*;

# Copy built firmware to firmware folder
cp -r /home/atleia/Documents/master/agilio/modified-nic-firmware/nic-firmware/firmware/nffw/* .;

# Copy firmware out of nic-folder and into main firmware folder. 
cp ./nic/* .;

# Reload firmware
echo "RELOADING FIRMWARE"

depmod -a;
rmmod nfp;
modprobe nfp nfp_dev_cpp=1;
update-initramfs -u;


