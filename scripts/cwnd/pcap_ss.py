# Parse slow start: packet, ack, cwnd, sndwnd, ssthresh information,
# in units of packets, from a pcap file.
#
# to produce the input file for this, run:
# tcpdump -l -nNqtt -r pcap_filename
#
# 
# ASSUMPTIONS / LIMITATIONS:
# - This works on slow start only
# - This assumes Reno congestion control, or any other that's doing
#   "normal" slow start without HyStart or anything like that (i.e.: not Linux Cubic)
# - the initial window is hardcoded here  :-)
# - the receiver window isn't parsed (though that wouldn't be hard to add):
#   i.e., a greedy sender is assumed.
#
#
# Author: Michael Welzl, http://www.welzl.at
#
#
# Constants:
cwnd = float(10.0)

import sys


def same_address(address, from_pcap):
    index = -1

    if address[-1]=="X":
        for i in range(len(from_pcap)):
            if from_pcap[len(from_pcap)-1-i]==".":
                index = len(from_pcap)-1-i
                break

#        print("comparing:", address[0:-2], "with", from_pcap[0:index])
#        print(address[0:-2] == from_pcap[0:index])
#        sys.exit()
        return address[0:-2]==from_pcap[0:index]
    else:
        return address == from_pcap



if len(sys.argv)!=7:
    print("Parameters: filename source src_port destination dst_port mss")
    print("Any port: use X  (instead of * - less problematic in scripts)")
    sys.exit()

filename = sys.argv[1]
src = sys.argv[2] + "." + sys.argv[3]
dst = sys.argv[4] + "." + sys.argv[5]
mss = float(sys.argv[6])

try:
    infile = open(filename, "r")

    #######################################################################
    # Find the first lost packet's seqno., and when the loss was
    # detected by the sender. In doing so, also set firstTime
    #######################################################################

    line = infile.readline().replace(",", "").split()
    prev_ackno = int(-1); loss_seqno = int(-1)
    firstTime = float(-1); first_seqno = float(-1)

    bulk_started = False
    
    while len(line)>0:
        # Everything begins with the first sent data packet.
        if not ( ("S" in line[6]) or ("F" in line[6]) ):
            if not bulk_started and same_address(src, line[2]):
                try:
                    length_idx = line.index("length")
                    payload_len = int(line[length_idx + 1])
                    if payload_len >= 1000:
                        bulk_started = True
                except (ValueError, IndexError):
                    pass

            # Only set firstTime after bulk has started
            if firstTime < 0 and bulk_started and same_address(src, line[2]) and line[7]=="seq":
                firstTime = float(line[0])
                first_seqno = float(line[8].split(":")[0])

        if bulk_started and same_address(dst, line[2]) and line[7]=="ack":
            ackno = int(line[8])
            if ackno <= prev_ackno:
                loss_seqno = prev_ackno
                break
            prev_ackno = ackno

        line = infile.readline().replace(",", "").split()
    infile.seek(0)



    #######################################################################
    # All the rest  :-)
    #######################################################################

    prev_seqno = first_seqno; prev_ackno = first_seqno
    sndwnd = cwnd; loss = False

    line = infile.readline().replace(",", "").split()
    while len(line)>0:
        time = float(line[0])
        if (not ( ("S" in line[6]) or ("F" in line[6]) )) and time >= firstTime:

            if same_address(src, line[2]) and line[7]=="seq":
                seqnos = line[8].split(":")
                seqnos[0]=float(seqnos[0]); seqnos[1]=float(seqnos[1])

                # When a retransmission is detected, slow start has exited.
                # Print the final cwnd achieved and stop parsing.
                if seqnos[1] <= prev_seqno:
                    print(cwnd)
                    break
                prev_seqno = seqnos[1]

                sent = (seqnos[1]-seqnos[0])/mss
                sndwnd -= sent

            elif same_address(dst, line[2]) and line[7]=="ack":

                ackno = float(line[8])
                acked = (ackno-prev_ackno)/mss
                prev_ackno=ackno
                cwnd += acked
                sndwnd += 2.0*acked     # ack-clocking and cwnd incr

        line = infile.readline().replace(",", "").split()

    infile.close()

except IOError:
    print("couldn't read the input file.")

