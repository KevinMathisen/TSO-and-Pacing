#!/bin/bash
DOWNLOAD_FILE="ftp_download_file_250K.txt"
PCAP_FILE="dump.pcap"

# Start packet capture
tcpdump -i enp2s0np0 -w $PCAP_FILE -v tcp&

sleep 1

# Initiate desired number of ftp transfers to server at 10.0.0.2
for i in $(seq 0 0);
do
    echo "STARTING FLOW $i"
    wget -4 -r --delete-after -P ftp_downloads_$i ftp://10.0.0.2/$DOWNLOAD_FILE&     # NOTE: DOWNLOADED FILES WILL BE DELETED
done

# NOTE: Process must be killed manually, since this will wait for tcpdump to finish
wait

kill $(ps -e | pgrep tcpdump);


