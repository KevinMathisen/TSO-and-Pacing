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
    while len(line)>0:
        # Everything begins with the first sent data packet.
        if not ( ("S" in line[6]) or ("F" in line[6]) ):
            if firstTime < 0 and same_address(src, line[2]) and line[7]=="seq":
                firstTime = float(line[0])
                first_seqno = float(line[8].split(":")[0])

        if same_address(dst, line[2]) and line[7]=="ack":
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
    prev_snd_time = float(-1.0); prev_ack_time = float(-1.0);

    line = infile.readline().replace(",", "").split()
    while len(line)>0:
        time = float(line[0])
        if (not ( ("S" in line[6]) or ("F" in line[6]) )) and time >= firstTime:

#           print((time-firstTime), end=" ")
            if same_address(src, line[2]) and line[7]=="seq":
                seqnos = line[8].split(":")
                seqnos[0]=float(seqnos[0]); seqnos[1]=float(seqnos[1])

                # Determine time gap
                snd_timegap = time - prev_snd_time if prev_snd_time > 0 else -1.0
                prev_snd_time = time

                if seqnos[1] <= prev_seqno:
                    print((time-firstTime), "ssthresh", cwnd/2.0, "snd_timegap", snd_timegap)
                    break
                prev_seqno = seqnos[1]

                sent = (seqnos[1]-seqnos[0])/mss
                sndwnd -= sent
    #                 seqnos[0] = float(seqnos[0].replace(",", ""))
    #                 seqnos[1] = float(seqnos[1].replace(",", ""))
                print((time-firstTime), "snd", sent,
                    "cwnd", cwnd, "sndwnd", sndwnd,  "snd_timegap", snd_timegap, end="")
                if seqnos[0] <= loss_seqno < seqnos[1] and not loss:
                    print(" firstloss seqno_range",
                        str(int(seqnos[0])) + ":" + str(int(seqnos[1])))
                    loss = True
                else:
                    print()

            elif same_address(dst, line[2]) and line[7]=="ack":

                # Determine time gap
                ack_timegap = time - prev_ack_time if prev_ack_time > 0 else -1.0
                prev_ack_time = time

                ackno = float(line[8])
                acked = (ackno-prev_ackno)/mss
                prev_ackno=ackno
                cwnd += acked
                sndwnd += 2.0*acked     # ack-clocking and cwnd incr
                print((time-firstTime), "ack", acked, "cwnd", cwnd, "sndwnd", sndwnd,
                     "ack_timegap", ack_timegap, end="")
                if ackno == loss_seqno:
                    print(" firstloss_dupack", "ackno", int(ackno))
                else:
                    print()


    # #                print(time-firstTime, (float(seqnos[1])-float(seqnos[0]) / float(mss) ) )

# end of reading loop
        line = infile.readline().replace(",", "").split()

    infile.close()

except IOError:
    print("couldn't read the input file.")

