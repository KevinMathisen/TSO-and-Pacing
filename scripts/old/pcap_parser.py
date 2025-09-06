import dpkt
import datetime

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


"""
This scripts parses pcaps and generates appropriate plots.
The script is pretty messy, and much of the existing code does not get used to plot the final figures.
Useful plots are prefixed with "FIGURE N:"
"""


def plot_y_per_x(pcaps_per_label, get_y_per_x, fig_name, clear_plot=True, save_fig=True, label_suffix="", is_x_log=True, is_y_log=False, xlabel=None, ylabel=None, x_unit=None, y_unit=None, title=None, scale_to_us=False):
    if clear_plot:
        plt.clf()

    for label in pcaps_per_label:
        pcap = pcaps_per_label[label]

        y_per_x = get_y_per_x(pcap)

        x_values = sorted(list(y_per_x.keys()))
        y_values = []

        for x in x_values:
            avg = y_per_x[x]['avg']
            if (scale_to_us):
                avg *= 1000000
            y_values.append(avg)

        if (is_x_log):
            plt.xscale("log")
        if (is_y_log):
            plt.yscale("log")
        plt.plot(x_values, y_values, label=(label + label_suffix))

    if (save_fig):
        plt.title(title)

        if xlabel is not None:
            plt.xlabel(xlabel)

        if ylabel is not None:
            plt.ylabel(ylabel)

        if y_unit is not None:
            plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter(y_unit))

        if x_unit is not None:
            plt.gca().xaxis.set_major_formatter(mticker.FormatStrFormatter(x_unit))

        plt.legend(loc="best")
        plt.savefig(fig_name)


def read_packets(pcap_name):
    packets = []
    packet_counter = 1
    for ts, packet in dpkt.pcap.Reader(open(pcap_name, 'rb')):
        eth = dpkt.ethernet.Ethernet(packet)

        packets.append({"ts": ts, "n": packet_counter, "tcp": eth.data.data, 'rt': False, 'mapped_to_pair': False})

        packet_counter += 1

    return packets


MSS = 1448

def get_client_ports(server_packets):
    client_ports = []
    for packet in server_packets:
        tcp = packet['tcp']
        app = tcp.data

        if len(app) > MSS:
            if tcp.dport not in client_ports:
                client_ports.append(tcp.dport)

    return client_ports


def get_client_packets_by_port(client_packets, client_ports):
    client_packets_by_port = {}
    for packet in client_packets:
        if packet['tcp'].dport in client_ports:
            if packet['tcp'].dport not in client_packets_by_port:
                client_packets_by_port[packet['tcp'].dport] = []
            client_packets_by_port[packet['tcp'].dport].append(packet)

    return client_packets_by_port


def get_server_packets_by_port(server_packets, client_ports):
    server_packets_by_port = {}
    for packet in server_packets:
        if packet['tcp'].dport in client_ports:
            if packet['tcp'].dport not in server_packets_by_port.keys():
                server_packets_by_port[packet['tcp'].dport] = []

            if len(packet['tcp'].data) > MSS:
                packet['tso'] = 1
                server_packets_by_port[packet['tcp'].dport].append(packet)

                seq = packet['tcp'].seq
                next_seq = seq + len(packet['tcp'].data)

                seq += MSS

                segment_counter = 2
                while seq < next_seq:
                    fake_tcp = dpkt.tcp.TCP()
                    fake_tcp.seq = seq
                    fake_tcp.flags = packet['tcp'].flags
                    fake_tcp.opts = packet['tcp'].opts
                    fake_tcp.dport = packet['tcp'].dport
                    fake_packet = {'tcp': fake_tcp, 'ts': packet['ts'], 'n': packet['n'], 'tso': segment_counter}

                    server_packets_by_port[packet['tcp'].dport].append(fake_packet)

                    seq += MSS
                    segment_counter += 1
            else:
                packet['tso'] = 0
                server_packets_by_port[packet['tcp'].dport].append(packet)

    return server_packets_by_port


def get_client_retransmitted_packets_by_port(client_ports, client_packets_by_port):
    client_retransmitted_packets_by_port = {}

    for dport in client_ports:
        client_retransmitted_packets_by_port[dport] = []

        for i, packet in enumerate(client_packets_by_port[dport]):
            for j in range(0, i):
                other_packet = client_packets_by_port[dport][j]
                if other_packet['tcp'].seq == packet['tcp'].seq:
                    client_retransmitted_packets_by_port[dport].append(packet)
                    break

    return client_retransmitted_packets_by_port


def count_sum(list):
    sum = 0

    # print(list)

    for x in list:
        # print("x",x)
        sum += x

    return sum

def merge_entries_by_port(entries_by_port):
    merged = []

    for dport in entries_by_port.keys():
        for x in entries_by_port[dport]:
            merged.append(x)

    return merged
def count_sum_per_port(values_by_port, client_ports):
    sum_per_port = {}

    for dport in client_ports:
        sum_per_port[dport] = 0

        for value in values_by_port[dport]:
            sum_per_port[dport] += value

    return sum_per_port

def count_average_per_port(values_by_port, client_ports):
    avg_per_port = {}

    sum_per_port = count_sum_per_port(values_by_port, client_ports)

    for dport in client_ports:
        avg_per_port[dport] = sum_per_port[dport] / len(values_by_port[dport])

    return avg_per_port

def count_total_packets_from_all_ports(packets_by_port, client_ports):
    total_packets = 0

    for dport in client_ports:
        total_packets += len(packets_by_port[dport])

    return total_packets



def get_client_total_packets(client_packets_by_port, client_ports):
    client_total_packets = 0

    for dport in client_ports:
        client_total_packets += len(client_packets_by_port[dport])

    return client_total_packets

def get_server_total_packets(server_packets_by_port, client_ports):
    server_total_packets = 0
    for dport in client_ports:
        server_total_packets += len(server_packets_by_port[dport])

    return server_total_packets



def get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports):
    server_retransmitted_packets_by_port = {}
    for dport in client_ports:
        server_retransmitted_packets_by_port[dport] = []

        print("port", dport)

        for i, packet in enumerate(server_packets_by_port[dport]):

            is_retransmit = False

            server_packets_by_port[dport][i]['rt'] = False

            for j in range(0, i):
                other_packet = server_packets_by_port[dport][j]
                if other_packet['tcp'].seq == packet['tcp'].seq:
                    server_retransmitted_packets_by_port[dport].append(packet)

                    server_packets_by_port[dport][i]['rt'] = True

                    is_retransmit = True
                    break

    return server_retransmitted_packets_by_port


def get_lost_packets(server_packets_to_client_packets_by_port, client_ports):
    lost_packets_by_port = {}

    for dport in client_ports:
        lost_packets_by_port[dport] = []

        for packet_map in server_packets_to_client_packets_by_port[dport]:
            if packet_map['client'] is None:
                lost_packets_by_port[dport].append(packet_map['server'])

            print("Lost packet", packet_map['server']['n'], "tso", packet_map['server']['tso'])

    return lost_packets_by_port


def get_transmitted_multiple_received_once_by_port(server_packets_by_port, server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports, client_packets_by_port):
    lost_packets = {}
    for dport in client_ports:
        lost_packets[dport] = [pkt for pkt in server_retransmitted_packets_by_port[dport]]

        for client_packet_i in range(len(client_retransmitted_packets_by_port[dport]) - 1, -1, -1):
            client_packet = client_retransmitted_packets_by_port[dport][client_packet_i]

            if (client_packet['tcp'].seq == 3401642321):
                print("Checking client packet with seq 13033 (n=", client_packet['n'])

            for lost_packet_i in range(0, len(lost_packets[dport])):
                lost_packet = lost_packets[dport][lost_packet_i]

                # Packet that was transmitted multiple times by server was not spurious, since was received
                # by client
                if lost_packet['tcp'].seq == client_packet['tcp'].seq:
                    lost_packets[dport].pop(lost_packet_i)

                    print("Packet with seq", lost_packet['tcp'].seq, "(", lost_packet['n'], ") was not lost")

                    break

    print("NEW TRANSMITTED MULTIPLE RECV ONCE")
    for dport in client_ports:
        print(dport, ":", len(lost_packets[dport]))
        for pkt in lost_packets[dport]:
            print(pkt['n'])

    return lost_packets


def get_spurious_retransmissions_by_port(server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports):
    spurious_retransmissions = {}
    for dport in client_ports:
        spurious_retransmissions[dport] = []

        server_retransmissions = [pkt for pkt in server_retransmitted_packets_by_port[dport]]

        for client_packet in client_retransmitted_packets_by_port[dport]:
            for i in range(0, len(server_retransmissions)):
                server_retransmission = server_retransmissions[i]

                if server_retransmission['tcp'].seq == client_packet['tcp'].seq:
                    spurious_retransmissions[dport].append(server_retransmission)
                    server_retransmissions.pop(i)
                    break

    for dport in client_ports:
        print("Spurious RTs: port", dport, "count:", len(spurious_retransmissions[dport]))

        for packet in spurious_retransmissions[dport]:
            print("spurious:", packet['n'])

    return spurious_retransmissions



def get_server_tso_packets(server_packets, client_ports):
    server_tso_segment_counter = 0
    server_tso_packet_counter = 0
    server_tso_packets = {}
    for packet in server_packets:
        if packet['tcp'].dport in client_ports:
            if packet['tcp'].dport not in server_tso_packets.keys():
                server_tso_packets[packet['tcp'].dport] = []

            if len(packet['tcp'].data) > MSS:
                server_tso_segment_counter += 1
                server_tso_packet_counter += 1

                tso_packet = []

                packet['tso'] = 1
                tso_packet.append(packet)

                seq = packet['tcp'].seq
                next_seq = seq + len(packet['tcp'].data)

                seq += MSS

                while seq < next_seq:
                    fake_tcp = dpkt.tcp.TCP()
                    fake_tcp.seq = seq
                    fake_packet = {'tcp': fake_tcp, 'ts': packet['ts'], 'n': packet['n']}

                    tso_packet.append(fake_packet)

                    seq += MSS

                    server_tso_segment_counter += 1

                server_tso_packets[packet['tcp'].dport].append(tso_packet)

    check_for_duplicate_server_tso_segments(client_ports, server_tso_packets)

    return server_tso_packets


def check_for_duplicate_server_tso_segments(client_ports, server_tso_packets):
    for dport in client_ports:
        for i, tso_packet in enumerate(server_tso_packets[dport]):
            for segment in tso_packet:
                for other_tso_packet in server_tso_packets[dport][i + 1:]:
                    for other_segment in other_tso_packet:
                        if segment['tcp'].seq == other_segment['tcp'].seq:
                            print("FOUND DUPLICATE SEGMENT", segment['n'], segment['tcp'].seq, other_segment['n'],
                                  other_segment['tcp'].seq)


def get_client_tso_packets_without_timestamps(client_ports, server_tso_packets, client_packets_by_port):
    client_tso_packets = {}
    for dport in client_ports:
        client_tso_packets[dport] = []

        for server_packet in server_tso_packets[dport]:
            client_tso_packet = []

            for server_segment in server_packet:

                matching_client_segments = []
                for client_segment in client_packets_by_port[dport]:
                    if client_segment['tcp'].seq == server_segment['tcp'].seq:
                        matching_client_segments.append(client_segment)

                # Removing client segments received before server segment was transmitted
                matching_client_segments = list(
                    filter(lambda p: ((p['ts'] - server_segment['ts']) > 0), matching_client_segments))

                # Sort by most similar time stamp to server segment
                matching_client_segments.sort(key=lambda p: (p['ts'] - server_segment['ts']))

                # Removing client segments with N smaller than previously found TSO segment
                if len(client_tso_packet) > 0:
                    matching_client_segments = list(
                        filter(lambda p: (p['n'] > client_tso_packet[-1]['n']), matching_client_segments))

                if len(matching_client_segments) > 0:
                    client_tso_packet.append(matching_client_segments[0])

            if len(client_tso_packet) > 0:
                client_tso_packets[dport].append(client_tso_packet)

    return client_tso_packets


def get_client_tso_packets(server_packets_to_client_packets, client_ports):
    client_tso_packets = {}

    for dport in client_ports:
        client_tso_packets[dport] = []

        client_tso_packet = []

        for packet_map in server_packets_to_client_packets[dport]:
            server_packet = packet_map['server']
            client_packet = packet_map['client']

            # got new tso packet: store previously found tso packets
            if server_packet['tso'] == 1:
                if len(client_tso_packet) > 0:
                    client_tso_packets[dport].append(client_tso_packet)
                client_tso_packet = []

            if server_packet['tso'] > 0:
                if client_packet is not None:
                    client_tso_packet.append(client_packet)

    # Check if there are still duplicate tso segments
    for dport in client_tso_packets.keys():
        print(dport)
        for tso_packet in client_tso_packets[dport]:
            duplicates = 0
            for segment in tso_packet:
                seq = segment['tcp'].seq
                i = 0
                for comp_segment in tso_packet:
                    if comp_segment['tcp'].seq == seq:
                        i += 1

                if i > 1:
                    duplicates += 1

            if (duplicates > 0):
                print("DUPLICATES", duplicates, "first n:", tso_packet[0]['n'])

    return client_tso_packets


# Map server transmissions to client receptions: This appears to be somewhat unreliable, so avoid if possible
def map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports):
    server_packets_to_client_packets = {}
    for dport in client_ports:
        print(dport)

        server_packets_to_client_packets[dport] = []

        for server_packet in server_packets_by_port[dport]:
            server_options = dpkt.tcp.parse_opts(server_packet['tcp'].opts)
            server_ts_option = list(filter(lambda opt: (opt[0] == dpkt.tcp.TCP_OPT_TIMESTAMP), server_options))
            # print("filtered server options", server_options)
            if (len(server_options) == 0):
                print(server_packet['n'], server_packet['tcp'].seq, server_packet['tcp'])
            server_ts_option = server_ts_option[0][1]

            packet_map = {'server': server_packet, 'client': None}

            matching_client_segments = []

            for client_packet in client_packets_by_port[dport]:
                client_options = dpkt.tcp.parse_opts(client_packet['tcp'].opts)
                client_ts_option = list(filter(lambda opt: (opt[0] == dpkt.tcp.TCP_OPT_TIMESTAMP), client_options))[0][1]

                if client_packet['tcp'].seq == server_packet['tcp'].seq and client_ts_option == server_ts_option:
                    matching_client_segments.append(client_packet)

            if len(matching_client_segments) > 1:
                # Removing client segments received before server segment was transmitted
                matching_client_segments = list(
                    filter(lambda p: ((p['ts'] - server_packet['ts']) > 0), matching_client_segments))

                # Sort by most similar time stamp to server segment
                matching_client_segments.sort(key=lambda p: (p['ts'] - server_packet['ts']))

            if len(matching_client_segments) > 0:
                packet_map['client'] = matching_client_segments[0]

            # Tagging packet
            packet_map['server']['mapped_to_pair'] = True
            if packet_map['client'] is not None:
                packet_map['client']['mapped_to_pair'] = True  # checking number of packets that dont get matched to a server packet

            server_packets_to_client_packets[dport].append(packet_map)

    # CHECKING HOW MANY CLIENT PACKETS WERE NOT MAPPED TO A CORRESPONDING SERVER PACKET
    print("CLIENT PACKETS NOT MATCHED:",
          len(list(filter(lambda p: (not p['mapped_to_pair']), merge_entries_by_port(client_packets_by_port)))),
          "TOTAL CLIENT PACKETS:", len(merge_entries_by_port(client_packets_by_port)))

    # Check if a server packet has been mapped to a client packet that was received before it was transmitted
    for dport in client_ports:
        print(dport)
        for packet_pair in server_packets_to_client_packets[dport]:
            if packet_pair['client'] is not None:
                if packet_pair['client']['ts'] < packet_pair['server']['ts']:
                    print("SERVER PACKET", packet_pair['server']['n'], "is mapped to client packet with smaller timestamp", packet_pair['client']['n'], "port", packet_pair['server']['tcp'].dport)

    return server_packets_to_client_packets


# PCAPS

flows_unmodified_firmware_pcaps = {
    "1MB unmodified": {
        1: {"server": "server_pcaps/1m_og_fw_1flow/server_1m_og_fw_1flow",
            "client": "client_pcaps/1m_og_fw_1flow/client_1m_og_fw_1flow"},
        2: {"server": "server_pcaps/1m_og_fw_2flow/server_1m_og_fw_2flow",
            "client": "client_pcaps/1m_og_fw_2flow/client_1m_og_fw_2flow"},
        3: {"server": "server_pcaps/1m_og_fw_3flow/server_1m_og_fw_3flow",
            "client": "client_pcaps/1m_og_fw_3flow/client_1m_og_fw_3flow"},
    }
}

flows_no_pace_pcaps = {
    "1MB modified 0ms": {
        1: {"server": "server_pcaps/1m_no_pace_1flow/server_1m_no_pace_1flow",
            "client": "client_pcaps/1m_no_pace_1flow/client_1m_no_pace_1flow"},
        2: {"server": "server_pcaps/1m_no_pace_2flow/server_1m_no_pace_2flow",
            "client": "client_pcaps/1m_no_pace_2flow/client_1m_no_pace_2flow"},
        3: {"server": "server_pcaps/1m_no_pace_3flow/server_1m_no_pace_3flow",
            "client": "client_pcaps/1m_no_pace_3flow/client_1m_no_pace_3flow"},
    }
}

packet_queue_length_pcaps = {
    "1MB full pace 1ms 3 flows":
        {80: {"server": "server_pcaps/1m_full_pace_1ms_3flow/server_1m_full_pace_1ms_3flow",
                "client": "client_pcaps/1m_full_pace_1ms_3flow/client_1m_full_pace_1ms_3flow"},
        40: {"server": "server_pcaps/1m_40_pkt_full_pace_1ms_3flow/server_1m_40pkt_full_pace_1ms_3flow",
              "client": "client_pcaps/1m_40pkt_full_pace_1ms_3flow/client_1m_40_pkt_full_pace_1ms_3flow"},
        20: {"server": "server_pcaps/1m_20_pkt_full_pace_1ms_3flow/server_1m_20pkt_full_pace_1ms_3flow",
              "client": "client_pcaps/1m_20pkt_full_pace_1ms_3flow/client_1m_20_pkt_full_pace_1ms_3flow"},
        10: {"server": "server_pcaps/1m_10_pkt_full_pace_1ms_3flow/server_1m_10pkt_full_pace_1ms_3flow",
              "client": "client_pcaps/1m_10pkt_full_pace_1ms_3flow/client_1m_10_pkt_full_pace_1ms_3flow"}},

    "1MB full pace 0.1ms 3 flows":
        {80: {"server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
              "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"},
        40: {"server": "server_pcaps/1m_40_pkt_full_pace_01ms_3flow/server_1m_40pkt_full_pace_01ms_3flow",
              "client": "client_pcaps/1m_40pkt_full_pace_01ms_3flow/client_1m_40pkt_full_pace_01ms_3flow"},
        20: {"server": "server_pcaps/1m_20_pkt_full_pace_01ms_3flow/server_1m_20pkt_full_pace_01ms_3flow",
              "client": "client_pcaps/1m_20pkt_full_pace_01ms_3flow/client_1m_20pkt_full_pace_01ms_3flow"},
        10: {"server": "server_pcaps/1m_10_pkt_full_pace_01ms_3flow/server_1m_10pkt_full_pace_01ms_3flow",
              "client": "client_pcaps/1m_10pkt_full_pace_01ms_3flow/client_1m_10pkt_full_pace_01ms_3flow"}},

"1MB TSO pace 1ms 3 flows":
        {80: {"server": "server_pcaps/1m_tso_pace_1ms_3flow/server_1m_tso_pace_1ms_3flow",
                "client": "client_pcaps/1m_tso_pace_1ms_3flow/client_1m_tso_pace_1ms_3flow"},
        40: {"server": "server_pcaps/1m_40_pkt_tso_pace_1ms_3flow/server_1m_40pkt_tso_pace_1ms_3flow",
              "client": "client_pcaps/1m_40pkt_tso_pace_1ms_3flow/client_1m_40_pkt_tso_pace_1ms_3flow"},
        20: {"server": "server_pcaps/1m_20_pkt_tso_pace_1ms_3flow/server_1m_20pkt_tso_pace_1ms_3flow",
              "client": "client_pcaps/1m_20pkt_tso_pace_1ms_3flow/client_1m_20_pkt_tso_pace_1ms_3flow"},
        10: {"server": "server_pcaps/1m_10_pkt_tso_pace_1ms_3flow/server_1m_10pkt_tso_pace_1ms_3flow",
              "client": "client_pcaps/1m_10pkt_tso_pace_1ms_3flow/client_1m_10_pkt_tso_pace_1ms_3flow"}},

    "1MB TSO pace 0.1ms 3 flows":
        {80: {"server": "server_pcaps/1m_tso_pace_01ms_3flow/server_1m_tso_pace_01ms_3flow",
              "client": "client_pcaps/1m_tso_pace_01ms_3flow/client_1m_tso_pace_01ms_3flow"},
        40: {"server": "server_pcaps/1m_40_pkt_tso_pace_01ms_3flow/server_1m_40pkt_tso_pace_01ms_3flow",
              "client": "client_pcaps/1m_40pkt_tso_pace_01ms_3flow/client_1m_40pkt_tso_pace_01ms_3flow"},
        20: {"server": "server_pcaps/1m_20_pkt_tso_pace_01ms_3flow/server_1m_20pkt_tso_pace_01ms_3flow",
              "client": "client_pcaps/1m_20pkt_tso_pace_01ms_3flow/client_1m_20pkt_tso_pace_01ms_3flow"},
        10: {"server": "server_pcaps/1m_10_pkt_tso_pace_01ms_3flow/server_1m_10pkt_tso_pace_01ms_3flow",
              "client": "client_pcaps/1m_10pkt_tso_pace_01ms_3flow/client_1m_10pkt_tso_pace_01ms_3flow"}},
}

packet_delay_pcaps = {
    "Pace-all 3 flows": {
        100000: {"server": "server_pcaps/1m_full_pace_100ms_3flow/server_1m_full_pace_100ms_3flow",
              "client": "client_pcaps/1m_full_pace_100ms_3flow/client_1m_full_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_3flow/server_1m_full_pace_10ms_3flow",
              "client": "client_pcaps/1m_full_pace_10ms_3flow/client_1m_full_pace_10ms_3flow"},

        1000: {"server": "server_pcaps/1m_full_pace_1ms_3flow/server_1m_full_pace_1ms_3flow",
                "client": "client_pcaps/1m_full_pace_1ms_3flow/client_1m_full_pace_1ms_3flow"},
        100: {"server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
                "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"},

        10: {"server": "server_pcaps/1m_full_pace_001ms_3flow/server_1m_full_pace_001ms_3flow",
              "client": "client_pcaps/1m_full_pace_001ms_3flow/client_1m_full_pace_001ms_3flow"},
        1: {"server": "server_pcaps/1m_full_pace_0001ms_3flow/server_1m_full_pace_0001ms_3flow",
              "client": "client_pcaps/1m_full_pace_0001ms_3flow/client_1m_full_pace_0001ms_3flow"}
    },

    # "Pace-all 2 flows": {
    #     1000: {"server": "server_pcaps/1m_full_pace_1ms_2flow/server_1m_full_pace_1ms_2flow",
    #             "client": "client_pcaps/1m_full_pace_1ms_2flow/client_1m_full_pace_1ms_2flow"},
    #     100: {"server": "server_pcaps/1m_full_pace_01ms_2flow/server_1m_full_pace_01ms_2flow",
    #             "client": "client_pcaps/1m_full_pace_01ms_2flow/client_1m_full_pace_01ms_2flow"},
    #     },
#         #
#         # 10: {"server": "server_pcaps/1m_full_pace_001ms_2flow/server_1m_full_pace_001ms_2flow",
#         #       "client": "client_pcaps/1m_full_pace_001ms_2flow/client_1m_full_pace_001ms_2flow"},
#         # 1: {"server": "server_pcaps/1m_full_pace_0001ms_2flow/server_1m_full_pace_0001ms_2flow",
#         #       "client": "client_pcaps/1m_full_pace_0001ms_2flow/client_1m_full_pace_0001ms_2flow"}},

    "Pace-all 1 flow": {
        100000: {"server": "server_pcaps/1m_full_pace_100ms_1flow/server_1m_full_pace_100ms_1flow",
                      "client": "client_pcaps/1m_full_pace_100ms_1flow/client_1m_full_pace_100ms_1flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_1flow/server_1m_full_pace_10ms_1flow",
                      "client": "client_pcaps/1m_full_pace_10ms_1flow/client_1m_full_pace_10ms_1flow"},

        1000: {"server": "server_pcaps/1m_full_pace_1ms_1flow/server_1m_full_pace_1ms_1flow",
                "client": "client_pcaps/1m_full_pace_1ms_1flow/client_1m_full_pace_1ms_1flow"},
        100: {"server": "server_pcaps/1m_full_pace_01ms_1flow/server_1m_full_pace_01ms_1flow",
                "client": "client_pcaps/1m_full_pace_01ms_1flow/client_1m_full_pace_01ms_1flow"},
        10: {"server": "server_pcaps/1m_full_pace_001ms_1flow/server_1m_full_pace_001ms_1flow",
              "client": "client_pcaps/1m_full_pace_001ms_1flow/client_1m_full_pace_001ms_1flow"},
        1: {"server": "server_pcaps/1m_full_pace_0001ms_1flow/server_1m_full_pace_0001ms_1flow",
              "client": "client_pcaps/1m_full_pace_0001ms_1flow/client_1m_full_pace_0001ms_1flow"}
    },

    "Pace-TSO 3 flows": {
        100000: {"server": "server_pcaps/1m_tso_pace_100ms_3flow/server_1m_tso_pace_100ms_3flow",
                 "client": "client_pcaps/1m_tso_pace_100ms_3flow/client_1m_tso_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_3flow/server_1m_tso_pace_10ms_3flow",
                      "client": "client_pcaps/1m_tso_pace_10ms_3flow/client_1m_tso_pace_10ms_3flow"},

        1000: {"server": "server_pcaps/1m_tso_pace_1ms_3flow/server_1m_tso_pace_1ms_3flow",
                "client": "client_pcaps/1m_tso_pace_1ms_3flow/client_1m_tso_pace_1ms_3flow"},
        100: {"server": "server_pcaps/1m_tso_pace_01ms_3flow/server_1m_tso_pace_01ms_3flow",
                "client": "client_pcaps/1m_tso_pace_01ms_3flow/client_1m_tso_pace_01ms_3flow"},

        10: {"server": "server_pcaps/1m_tso_pace_001ms_3flow/server_1m_tso_pace_001ms_3flow",
              "client": "client_pcaps/1m_tso_pace_001ms_3flow/client_1m_tso_pace_001ms_3flow"},
        1: {"server": "server_pcaps/1m_tso_pace_0001ms_3flow/server_1m_tso_pace_0001ms_3flow",
              "client": "client_pcaps/1m_tso_pace_0001ms_3flow/client_1m_tso_pace_0001ms_3flow"}
    },

    # "1MB TSO pace 2 flows": {
    #
    #     1000: {"server": "server_pcaps/1m_tso_pace_1ms_2flow/server_1m_tso_pace_1ms_2flow",
    #             "client": "client_pcaps/1m_tso_pace_1ms_2flow/client_1m_tso_pace_1ms_2flow"},
    #      100: {"server": "server_pcaps/1m_tso_pace_01ms_2flow/server_1m_tso_pace_01ms_2flow",
    #             "client": "client_pcaps/1m_tso_pace_01ms_2flow/client_1m_tso_pace_01ms_2flow"},
    #     },
    #
    # # 10: {"server": "server_pcaps/1m_tso_pace_001ms_1flow/server_1m_tso_pace_001ms_1flow",
    # #       "client": "client_pcaps/1m_tso_pace_001ms_1flow/client_1m_tso_pace_001ms_1flow"},
    # # 1: {"server": "server_pcaps/1m_tso_pace_0001ms_1flow/server_1m_tso_pace_0001ms_1flow",
    # #       "client": "client_pcaps/1m_tso_pace_0001ms_1flow/client_1m_tso_pace_0001ms_1flow"}},

    "Pace-TSO 1 flow": {
        100000: {"server": "server_pcaps/1m_tso_pace_100ms_1flow/server_1m_tso_pace_100ms_1flow",
                      "client": "client_pcaps/1m_tso_pace_100ms_1flow/client_1m_tso_pace_100ms_1flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_1flow/server_1m_tso_pace_10ms_1flow",
                      "client": "client_pcaps/1m_tso_pace_10ms_1flow/client_1m_tso_pace_10ms_1flow"},

        1000: {"server": "server_pcaps/1m_tso_pace_1ms_1flow/server_1m_tso_pace_1ms_1flow",
                "client": "client_pcaps/1m_tso_pace_1ms_1flow/client_1m_tso_pace_1ms_1flow"},
         100: {"server": "server_pcaps/1m_tso_pace_01ms_1flow/server_1m_tso_pace_01ms_1flow",
                "client": "client_pcaps/1m_tso_pace_01ms_1flow/client_1m_tso_pace_01ms_1flow"},

        10: {"server": "server_pcaps/1m_tso_pace_001ms_1flow/server_1m_tso_pace_001ms_1flow",
              "client": "client_pcaps/1m_tso_pace_001ms_1flow/client_1m_tso_pace_001ms_1flow"},
        1: {"server": "server_pcaps/1m_tso_pace_0001ms_1flow/server_1m_tso_pace_0001ms_1flow",
              "client": "client_pcaps/1m_tso_pace_0001ms_1flow/client_1m_tso_pace_0001ms_1flow"}
    },
}

packet_delay_without_1_pcaps = {
    "Pace-all 3 flows": {
        100000: {"server": "server_pcaps/1m_full_pace_100ms_3flow/server_1m_full_pace_100ms_3flow",
              "client": "client_pcaps/1m_full_pace_100ms_3flow/client_1m_full_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_3flow/server_1m_full_pace_10ms_3flow",
              "client": "client_pcaps/1m_full_pace_10ms_3flow/client_1m_full_pace_10ms_3flow"},

        1000: {"server": "server_pcaps/1m_full_pace_1ms_3flow/server_1m_full_pace_1ms_3flow",
                "client": "client_pcaps/1m_full_pace_1ms_3flow/client_1m_full_pace_1ms_3flow"},
        100: {"server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
                "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"},

        10: {"server": "server_pcaps/1m_full_pace_001ms_3flow/server_1m_full_pace_001ms_3flow",
              "client": "client_pcaps/1m_full_pace_001ms_3flow/client_1m_full_pace_001ms_3flow"},
        1: {"server": "server_pcaps/1m_full_pace_0001ms_3flow/server_1m_full_pace_0001ms_3flow",
              "client": "client_pcaps/1m_full_pace_0001ms_3flow/client_1m_full_pace_0001ms_3flow"}
    },

    # "Pace-all 2 flows": {
    #     1000: {"server": "server_pcaps/1m_full_pace_1ms_2flow/server_1m_full_pace_1ms_2flow",
    #             "client": "client_pcaps/1m_full_pace_1ms_2flow/client_1m_full_pace_1ms_2flow"},
    #     100: {"server": "server_pcaps/1m_full_pace_01ms_2flow/server_1m_full_pace_01ms_2flow",
    #             "client": "client_pcaps/1m_full_pace_01ms_2flow/client_1m_full_pace_01ms_2flow"},
    #     },
#         # 10: {"server": "server_pcaps/1m_full_pace_001ms_2flow/server_1m_full_pace_001ms_2flow",
#         #       "client": "client_pcaps/1m_full_pace_001ms_2flow/client_1m_full_pace_001ms_2flow"},
#         # 1: {"server": "server_pcaps/1m_full_pace_0001ms_2flow/server_1m_full_pace_0001ms_2flow",
#         #       "client": "client_pcaps/1m_full_pace_0001ms_2flow/client_1m_full_pace_0001ms_2flow"}},

    "Pace-all 1 flow": {
            100000: {"server": "server_pcaps/1m_full_pace_100ms_1flow/server_1m_full_pace_100ms_1flow",
                          "client": "client_pcaps/1m_full_pace_100ms_1flow/client_1m_full_pace_100ms_1flow"},
            10000: {"server": "server_pcaps/1m_full_pace_10ms_1flow/server_1m_full_pace_10ms_1flow",
                          "client": "client_pcaps/1m_full_pace_10ms_1flow/client_1m_full_pace_10ms_1flow"},

            1000: {"server": "server_pcaps/1m_full_pace_1ms_1flow/server_1m_full_pace_1ms_1flow",
                    "client": "client_pcaps/1m_full_pace_1ms_1flow/client_1m_full_pace_1ms_1flow"},
            100: {"server": "server_pcaps/1m_full_pace_01ms_1flow/server_1m_full_pace_01ms_1flow",
                    "client": "client_pcaps/1m_full_pace_01ms_1flow/client_1m_full_pace_01ms_1flow"},
            10: {"server": "server_pcaps/1m_full_pace_001ms_1flow/server_1m_full_pace_001ms_1flow",
                  "client": "client_pcaps/1m_full_pace_001ms_1flow/client_1m_full_pace_001ms_1flow"},
            1: {"server": "server_pcaps/1m_full_pace_0001ms_1flow/server_1m_full_pace_0001ms_1flow",
                  "client": "client_pcaps/1m_full_pace_0001ms_1flow/client_1m_full_pace_0001ms_1flow"}
    },

    "Pace-TSO 3 flows": {
        100000: {"server": "server_pcaps/1m_tso_pace_100ms_3flow/server_1m_tso_pace_100ms_3flow",
                 "client": "client_pcaps/1m_tso_pace_100ms_3flow/client_1m_tso_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_3flow/server_1m_tso_pace_10ms_3flow",
                      "client": "client_pcaps/1m_tso_pace_10ms_3flow/client_1m_tso_pace_10ms_3flow"},

        1000: {"server": "server_pcaps/1m_tso_pace_1ms_3flow/server_1m_tso_pace_1ms_3flow",
                "client": "client_pcaps/1m_tso_pace_1ms_3flow/client_1m_tso_pace_1ms_3flow"},
        100: {"server": "server_pcaps/1m_tso_pace_01ms_3flow/server_1m_tso_pace_01ms_3flow",
                "client": "client_pcaps/1m_tso_pace_01ms_3flow/client_1m_tso_pace_01ms_3flow"},

        10: {"server": "server_pcaps/1m_tso_pace_001ms_3flow/server_1m_tso_pace_001ms_3flow",
              "client": "client_pcaps/1m_tso_pace_001ms_3flow/client_1m_tso_pace_001ms_3flow"},
        1: {"server": "server_pcaps/1m_tso_pace_0001ms_3flow/server_1m_tso_pace_0001ms_3flow",
              "client": "client_pcaps/1m_tso_pace_0001ms_3flow/client_1m_tso_pace_0001ms_3flow"}
    },

    # "1MB TSO pace 2 flows": {
    #     1000: {"server": "server_pcaps/1m_tso_pace_1ms_2flow/server_1m_tso_pace_1ms_2flow",
    #             "client": "client_pcaps/1m_tso_pace_1ms_2flow/client_1m_tso_pace_1ms_2flow"},
    #      100: {"server": "server_pcaps/1m_tso_pace_01ms_2flow/server_1m_tso_pace_01ms_2flow",
    #             "client": "client_pcaps/1m_tso_pace_01ms_2flow/client_1m_tso_pace_01ms_2flow"},
    #     },
    # # 10: {"server": "server_pcaps/1m_tso_pace_001ms_1flow/server_1m_tso_pace_001ms_1flow",
    # #       "client": "client_pcaps/1m_tso_pace_001ms_1flow/client_1m_tso_pace_001ms_1flow"},
    # # 1: {"server": "server_pcaps/1m_tso_pace_0001ms_1flow/server_1m_tso_pace_0001ms_1flow",
    # #       "client": "client_pcaps/1m_tso_pace_0001ms_1flow/client_1m_tso_pace_0001ms_1flow"}},

    "Pace-TSO 1 flow": {
        100000: {"server": "server_pcaps/1m_tso_pace_100ms_1flow/server_1m_tso_pace_100ms_1flow",
                      "client": "client_pcaps/1m_tso_pace_100ms_1flow/client_1m_tso_pace_100ms_1flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_1flow/server_1m_tso_pace_10ms_1flow",
                      "client": "client_pcaps/1m_tso_pace_10ms_1flow/client_1m_tso_pace_10ms_1flow"},

        1000: {"server": "server_pcaps/1m_tso_pace_1ms_1flow/server_1m_tso_pace_1ms_1flow",
                "client": "client_pcaps/1m_tso_pace_1ms_1flow/client_1m_tso_pace_1ms_1flow"},
         100: {"server": "server_pcaps/1m_tso_pace_01ms_1flow/server_1m_tso_pace_01ms_1flow",
                "client": "client_pcaps/1m_tso_pace_01ms_1flow/client_1m_tso_pace_01ms_1flow"},

        10: {"server": "server_pcaps/1m_tso_pace_001ms_1flow/server_1m_tso_pace_001ms_1flow",
              "client": "client_pcaps/1m_tso_pace_001ms_1flow/client_1m_tso_pace_001ms_1flow"},
        1: {"server": "server_pcaps/1m_tso_pace_0001ms_1flow/server_1m_tso_pace_0001ms_1flow",
              "client": "client_pcaps/1m_tso_pace_0001ms_1flow/client_1m_tso_pace_0001ms_1flow"}
    },
}

packet_queue_length_pcaps = {80: {"server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
                                  "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"},
                            40: {"server": "server_pcaps/1m_40_pkt_full_pace_01ms_3flow/server_1m_40pkt_full_pace_01ms_3flow",
                                  "client": "client_pcaps/1m_40pkt_full_pace_01ms_3flow/client_1m_40pkt_full_pace_01ms_3flow"},
                            20: {"server": "server_pcaps/1m_20_pkt_full_pace_01ms_3flow/server_1m_20pkt_full_pace_01ms_3flow",
                                  "client": "client_pcaps/1m_20pkt_full_pace_01ms_3flow/client_1m_20pkt_full_pace_01ms_3flow"},
                            10: {"server": "server_pcaps/1m_10_pkt_full_pace_01ms_3flow/server_1m_10pkt_full_pace_01ms_3flow",
                                  "client": "client_pcaps/1m_10pkt_full_pace_01ms_3flow/client_1m_10pkt_full_pace_01ms_3flow"}}

flows_large_file_pcaps = {
    "50M unmodified FW": {
        1: {"server": "server_pcaps/50m_og_fw_1flow/server_50m_og_fw_1flow",
                  "client": "client_pcaps/50m_og_fw_1flow/client_50m_og_fw_1flow"}
    },
    "50M modified 0ms": {
            1: {"server": "server_pcaps/50m_no_pace_1flow/server_50m_no_pace_1flow",
                "client": "client_pcaps/50m_no_pace_1flow/client_50m_no_pace_1flow"}
        }
}

long_packet_delay_pcaps = {
    "250K full pace 3 flows": {
        1000000: {"server": "server_pcaps/1m_full_pace_1000ms_3flow/server_250k_full_pace_1000ms_3flow",
                  "client": "client_pcaps/1m_full_pace_1000ms_3flow/client_1m_full_pace_1000ms_3flow"},
        # 500000: {"server": "server_pcaps/1m_full_pace_500ms_3flow/server_250k_full_pace_500ms_3flow",
        #         "client": "client_pcaps/1m_full_pace_500ms_3flow/client_1m_full_pace_500ms_3flow"},

    },
    "1MB full pace 3 flows": {
        100000: {"server": "server_pcaps/1m_full_pace_100ms_3flow/server_1m_full_pace_100ms_3flow",
              "client": "client_pcaps/1m_full_pace_100ms_3flow/client_1m_full_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_3flow/server_1m_full_pace_10ms_3flow",
              "client": "client_pcaps/1m_full_pace_10ms_3flow/client_1m_full_pace_10ms_3flow"},
    },

    "1MB full pace 1 flow": {
        1000: {"server": "server_pcaps/1m_full_pace_1ms_1flow/server_1m_full_pace_1ms_1flow",
                "client": "client_pcaps/1m_full_pace_1ms_1flow/client_1m_full_pace_1ms_1flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_1flow/server_1m_full_pace_10ms_1flow",
                  "client": "client_pcaps/1m_full_pace_10ms_1flow/client_1m_full_pace_10ms_1flow"},
        100000: {"server": "server_pcaps/1m_full_pace_100ms_1flow/server_1m_full_pace_100ms_1flow",
              "client": "client_pcaps/1m_full_pace_100ms_1flow/client_1m_full_pace_100ms_1flow"},
        10000: {"server": "server_pcaps/1m_full_pace_10ms_1flow/server_1m_full_pace_10ms_1flow",
              "client": "client_pcaps/1m_full_pace_10ms_1flow/client_1m_full_pace_10ms_1flow"},
        1000000: {"server": "server_pcaps/1m_full_pace_1000ms_1flow/server_250k_full_pace_1000ms_1flow",
                    "client": "client_pcaps/1m_full_pace_1000ms_1flow/client_1m_full_pace_1000ms_1flow"},
        500000: {"server": "server_pcaps/1m_full_pace_500ms_1flow/server_250k_full_pace_500ms_1flow",
                "client": "client_pcaps/1m_full_pace_500ms_1flow/client_1m_full_pace_500ms_1flow"},
    },

    "1MB TSO pace 3 flows": {
        1000000: {"server": "server_pcaps/1m_tso_pace_1000ms_3flow/server_1m_tso_pace_1000ms_3flow",
                "client": "client_pcaps/1m_tso_pace_1000ms_3flow/client_1m_tso_pace_1000ms_3flow"},
        500000: {"server": "server_pcaps/1m_tso_pace_500ms_3flow/server_1m_tso_pace_500ms_3flow",
                "client": "client_pcaps/1m_tso_pace_500ms_3flow/client_1m_tso_pace_500ms_3flow"},

        100000: {"server": "server_pcaps/1m_tso_pace_100ms_3flow/server_1m_tso_pace_100ms_3flow",
              "client": "client_pcaps/1m_tso_pace_100ms_3flow/client_1m_tso_pace_100ms_3flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_3flow/server_1m_tso_pace_10ms_3flow",
              "client": "client_pcaps/1m_tso_pace_10ms_3flow/client_1m_tso_pace_10ms_3flow"}},

    "1MB TSO pace 1 flow": {
        1000000: {"server": "server_pcaps/1m_tso_pace_1000ms_1flow/server_1m_tso_pace_1000ms_1flow",
                "client": "client_pcaps/1m_tso_pace_1000ms_1flow/client_1m_tso_pace_1000ms_1flow"},
         500000: {"server": "server_pcaps/1m_tso_pace_500ms_1flow/server_1m_tso_pace_500ms_1flow",
                "client": "client_pcaps/1m_tso_pace_500ms_1flow/client_1m_tso_pace_500ms_1flow"},

        100000: {"server": "server_pcaps/1m_tso_pace_100ms_1flow/server_1m_tso_pace_100ms_1flow",
              "client": "client_pcaps/1m_tso_pace_100ms_1flow/client_1m_tso_pace_100ms_1flow"},
        10000: {"server": "server_pcaps/1m_tso_pace_10ms_1flow/server_1m_tso_pace_10ms_1flow",
              "client": "client_pcaps/1m_tso_pace_10ms_1flow/client_1m_tso_pace_10ms_1flow"}},
}



flows_pcaps = {
    "1MB Full pace 1ms": {
        1: {
            "server": "server_pcaps/1m_full_pace_1ms_1flow/server_1m_full_pace_1ms_1flow",
            "client": "client_pcaps/1m_full_pace_1ms_1flow/client_1m_full_pace_1ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_full_pace_1ms_2flow/server_1m_full_pace_1ms_2flow",
            "client": "client_pcaps/1m_full_pace_1ms_2flow/client_1m_full_pace_1ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_full_pace_1ms_3flow/server_1m_full_pace_1ms_3flow",
            "client": "client_pcaps/1m_full_pace_1ms_3flow/client_1m_full_pace_1ms_3flow"
        }
    },
    "1MB Full pace 0.1ms": {
        1: {
            "server": "server_pcaps/1m_full_pace_01ms_1flow/server_1m_full_pace_01ms_1flow",
            "client": "client_pcaps/1m_full_pace_01ms_1flow/client_1m_full_pace_01ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_full_pace_01ms_2flow/server_1m_full_pace_01ms_2flow",
            "client": "client_pcaps/1m_full_pace_01ms_2flow/client_1m_full_pace_01ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
            "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"
        }
    },
    "1MB Full pace 0.01ms": {
        1: {
            "server": "server_pcaps/1m_full_pace_001ms_1flow/server_1m_full_pace_001ms_1flow",
            "client": "client_pcaps/1m_full_pace_001ms_1flow/client_1m_full_pace_001ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_full_pace_001ms_2flow/server_1m_full_pace_001ms_2flow",
            "client": "client_pcaps/1m_full_pace_001ms_2flow/client_1m_full_pace_001ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_full_pace_001ms_3flow/server_1m_full_pace_001ms_3flow",
            "client": "client_pcaps/1m_full_pace_001ms_3flow/client_1m_full_pace_001ms_3flow"
        }
    },
    "1MB Full pace 0.001ms": {
        1: {
            "server": "server_pcaps/1m_full_pace_0001ms_1flow/server_1m_full_pace_0001ms_1flow",
            "client": "client_pcaps/1m_full_pace_0001ms_1flow/client_1m_full_pace_0001ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_full_pace_0001ms_2flow/server_1m_full_pace_0001ms_2flow",
            "client": "client_pcaps/1m_full_pace_0001ms_2flow/client_1m_full_pace_0001ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_full_pace_0001ms_3flow/server_1m_full_pace_0001ms_3flow",
            "client": "client_pcaps/1m_full_pace_0001ms_3flow/client_1m_full_pace_0001ms_3flow"
        }
    },
    "1MB TSO pace 1ms": {
        1: {
            "server": "server_pcaps/1m_tso_pace_1ms_1flow/server_1m_tso_pace_1ms_1flow",
            "client": "client_pcaps/1m_tso_pace_1ms_1flow/client_1m_tso_pace_1ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_tso_pace_1ms_2flow/server_1m_tso_pace_1ms_2flow",
            "client": "client_pcaps/1m_tso_pace_1ms_2flow/client_1m_tso_pace_1ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_tso_pace_1ms_3flow/server_1m_tso_pace_1ms_3flow",
            "client": "client_pcaps/1m_tso_pace_1ms_3flow/client_1m_tso_pace_1ms_3flow"
        }
    },
    "1MB TSO pace 0.1ms": {
        1: {
            "server": "server_pcaps/1m_tso_pace_01ms_1flow/server_1m_tso_pace_01ms_1flow",
            "client": "client_pcaps/1m_tso_pace_01ms_1flow/client_1m_tso_pace_01ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_tso_pace_01ms_2flow/server_1m_tso_pace_01ms_2flow",
            "client": "client_pcaps/1m_tso_pace_01ms_2flow/client_1m_tso_pace_01ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_tso_pace_01ms_3flow/server_1m_tso_pace_01ms_3flow",
            "client": "client_pcaps/1m_tso_pace_01ms_3flow/client_1m_tso_pace_01ms_3flow"
        }
    },
    "1MB TSO pace 0.01ms": {
        1: {
            "server": "server_pcaps/1m_tso_pace_001ms_1flow/server_1m_tso_pace_001ms_1flow",
            "client": "client_pcaps/1m_tso_pace_001ms_1flow/client_1m_tso_pace_001ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_tso_pace_001ms_2flow/server_1m_tso_pace_001ms_2flow",
            "client": "client_pcaps/1m_tso_pace_001ms_2flow/client_1m_tso_pace_001ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_tso_pace_001ms_3flow/server_1m_tso_pace_001ms_3flow",
            "client": "client_pcaps/1m_tso_pace_001ms_3flow/client_1m_tso_pace_001ms_3flow"
        }
    },
    "1MB TSO pace 0.001ms": {
        1: {
            "server": "server_pcaps/1m_tso_pace_0001ms_1flow/server_1m_tso_pace_0001ms_1flow",
            "client": "client_pcaps/1m_tso_pace_0001ms_1flow/client_1m_tso_pace_0001ms_1flow"
        },
        2: {
            "server": "server_pcaps/1m_tso_pace_0001ms_2flow/server_1m_tso_pace_0001ms_2flow",
            "client": "client_pcaps/1m_tso_pace_0001ms_2flow/client_1m_tso_pace_0001ms_2flow"
        },
        3: {
            "server": "server_pcaps/1m_tso_pace_0001ms_3flow/server_1m_tso_pace_0001ms_3flow",
            "client": "client_pcaps/1m_tso_pace_0001ms_3flow/client_1m_tso_pace_0001ms_3flow"
        }
    },
    "1MB unmodified": {
            1: {"server": "server_pcaps/1m_og_fw_1flow/server_1m_og_fw_1flow",
                "client": "client_pcaps/1m_og_fw_1flow/client_1m_og_fw_1flow"},
            2: {"server": "server_pcaps/1m_og_fw_2flow/server_1m_og_fw_2flow",
                "client": "client_pcaps/1m_og_fw_2flow/client_1m_og_fw_2flow"},
            3: {"server": "server_pcaps/1m_og_fw_3flow/server_1m_og_fw_3flow",
                "client": "client_pcaps/1m_og_fw_3flow/client_1m_og_fw_3flow"},
        }
    ,
    "1MB modified 0ms": {
            1: {"server": "server_pcaps/1m_no_pace_1flow/server_1m_no_pace_1flow",
                "client": "client_pcaps/1m_no_pace_1flow/client_1m_no_pace_1flow"},
            2: {"server": "server_pcaps/1m_no_pace_2flow/server_1m_no_pace_2flow",
                "client": "client_pcaps/1m_no_pace_2flow/client_1m_no_pace_2flow"},
            3: {"server": "server_pcaps/1m_no_pace_3flow/server_1m_no_pace_3flow",
                "client": "client_pcaps/1m_no_pace_3flow/client_1m_no_pace_3flow"},
        }
}

flows_unmodified_modified_no_pace_pcaps = {"1MB unmodified": flows_pcaps["1MB unmodified"], "1MB modified 0ms": flows_pcaps["1MB modified 0ms"]}

average_throughput_bytes_per_sec_1flow = {
    "1MB Full pace": {
        1: 223010416,
        10: 101808858,
        100: 11290312,
        1000: 1144094,
        10000: 114436,
        100000: 11428
    },
    "1MB TSO pace": {
        1: 202994827,
        10: 116092368,
        100: 35161981,
        1000: 9598179,
        10000: 7783508,
        100000: 2019159
    }
}

packet_delay_full_pace_1flow_pcaps = {
    "Pace-all": packet_delay_pcaps["Pace-all 1 flow"],
}

packet_delay_tso_pace_1flow_pcaps = {
    "Pace-TSO ": packet_delay_pcaps["Pace-TSO 1 flow"],
}

long_packet_delay_full_pace_1flow_pcaps = {
    "Pace-all 1 flow": long_packet_delay_pcaps["1MB full pace 1 flow"],
    # "250K full pace 1 flow": long_packet_delay_pcaps["250K full pace 1 flow"]
}

packet_delay_3flow_pcaps = {
    "Pace-all 3 flows": packet_delay_pcaps["Pace-all 3 flows"],
    "Pace-TSO pace 3 flows": packet_delay_pcaps["Pace-TSO 3 flows"],
}

packet_delay_1flow_pcaps = {
    "Pace-all": packet_delay_pcaps["Pace-all 1 flow"],
    "Pace-TSO": packet_delay_pcaps["Pace-TSO 1 flow"],
}

flows_0001ms_pcaps = {"1MB TSO pace 0001ms": flows_pcaps["1MB TSO pace 0.001ms"], "1MB Full pace 0001ms": flows_pcaps["1MB Full pace 0.001ms"]}

delay_tso_pace_3flow_pcaps = {"1MB TSO pace 3 flows": packet_delay_pcaps["Pace-TSO 3 flows"]}
flows_tso_pace_pcaps = {"Pace-TSO 1000 μs": flows_pcaps["1MB TSO pace 1ms"], "Pace-TSO 100 μs": flows_pcaps["1MB TSO pace 0.1ms"],
                        "Pace-TSO 10 μs": flows_pcaps["1MB TSO pace 0.01ms"], "Pace-TSO 1 μs": flows_pcaps["1MB TSO pace 0.001ms"]}
flows_full_pace_pcaps = {"Pace-all 1000 μs": flows_pcaps["1MB Full pace 1ms"], "Pace-all 100 μs": flows_pcaps["1MB Full pace 0.1ms"],
                         "Pace-all pace 10 μs": flows_pcaps["1MB Full pace 0.01ms"], "Pace-all 1 μs": flows_pcaps["1MB Full pace 0.001ms"]}

flows_tso_pace_without_1_pcaps = {"Pace-TSO 1000 μs": flows_pcaps["1MB TSO pace 1ms"], "Pace-TSO 100 μs": flows_pcaps["1MB TSO pace 0.1ms"],
                        "Pace-TSO 10 μs": flows_pcaps["1MB TSO pace 0.01ms"]} #, "Pace-TSO 1 μs": flows_pcaps["1MB TSO pace 0.001ms"]}
flows_full_pace_without_1_pcaps = {"Pace-all 1000 μs": flows_pcaps["1MB Full pace 1ms"], "Pace-all 100 μs": flows_pcaps["1MB Full pace 0.1ms"],
                         "Pace-all pace 10 μs": flows_pcaps["1MB Full pace 0.01ms"]} #, "Pace-all 1 μs": flows_pcaps["1MB Full pace 0.001ms"]}

connection_entries_pcaps = {
    "Pace-all 100 μs 3 flows": {
        10: {"server": "server_pcaps/1m_full_pace_01ms_3flow/server_1m_full_pace_01ms_3flow",
            "client": "client_pcaps/1m_full_pace_01ms_3flow/client_1m_full_pace_01ms_3flow"},
        2: {"server": "server_pcaps/1m_2entry_full_pace_01ms_3flow/server_1m_2entry_full_pace_01ms_3flow",
             "client": "client_pcaps/1m_2entry_full_pace_01ms_3flow/client_1m_2entry_full_pace_01ms_3flow"},
        1: {"server": "server_pcaps/1m_1entry_full_pace_01ms_3flow/server_1m_1entry_full_pace_01ms_3flow",
            "client": "client_pcaps/1m_1entry_full_pace_01ms_3flow/client_1m_1entry_full_pace_01ms_3flow"}
    },
    "Pace-all 1000 μs 3 flows": {
            10: {"server": "server_pcaps/1m_full_pace_1ms_3flow/server_1m_full_pace_1ms_3flow",
                "client": "client_pcaps/1m_full_pace_1ms_3flow/client_1m_full_pace_1ms_3flow"},
            2: {"server": "server_pcaps/1m_2entry_full_pace_1ms_3flow/server_1m_2entry_full_pace_1ms_3flow",
                 "client": "client_pcaps/1m_2entry_full_pace_1ms_3flow/client_1m_2entry_full_pace_1ms_3flow"},
            1: {"server": "server_pcaps/1m_1entry_full_pace_1ms_3flow/server_1m_1entry_full_pace_1ms_3flow",
                "client": "client_pcaps/1m_1entry_full_pace_1ms_3flow/client_1m_1entry_full_pace_1ms_3flow"}
        }
}

def plot_throughput(dict):
    plt.clf()

    for label in dict.keys():
        y = []
        x = [delay for delay in dict[label].keys()]

        for delay in x:
            throughput = dict[label][delay]
            y.append(throughput)

        plt.xscale("log")
        plt.plot(x, y, label=label)

    plt.xlabel("Configured inter-packet gap (μs)")
    plt.ylabel("Throughput (Bps)")
    plt.legend(loc="best")
    plt.savefig("throughput_per_delay.png")

# FIGURE 14: Average throughput
plot_throughput(average_throughput_bytes_per_sec_1flow)


def get_premature_packets_by_port(server_packets_by_port, client_ports, delay_time_sec):
    premature_packets_by_port = {}
    for dport in client_ports:
        premature_packets_by_port[dport] = []

        tso_packet_i = 0

        while (tso_packet_i < len(server_packets_by_port[dport]) - 1):
            # Find last segment of next TSO packet
            while (server_packets_by_port[dport][tso_packet_i]['tso'] == 0 and (server_packets_by_port[dport][tso_packet_i]['tcp'].seq == server_packets_by_port[dport][tso_packet_i + 1]['tcp'].seq)):
                tso_packet_i += 1

            tso_packet = server_packets_by_port[dport][tso_packet_i]
            tso_transmission_time = tso_packet['ts'] + ((tso_packet['tso'] - 1) * delay_time_sec)

            premature_packet_i = tso_packet_i + 1

            # finding premature tso packets
            while premature_packet_i < len(server_packets_by_port[dport]) and (server_packets_by_port[dport][premature_packet_i]['ts'] < tso_transmission_time):
                if server_packets_by_port[dport][premature_packet_i]['tso'] < 2:
                    premature_packets_by_port[dport].append(server_packets_by_port[dport][premature_packet_i])

                premature_packet_i += 1

            tso_packet_i += 1

    return premature_packets_by_port

def get_unique_premature_packets_by_port(server_packets_by_port, client_ports, delay_time_sec):
    premature_packets_by_port = get_premature_packets_by_port(server_packets_by_port, client_ports, delay_time_sec)

    unique_premature_packets_by_port = {}

    for dport in client_ports:
        unique_premature_packets_by_port[dport] = []

        for packet in premature_packets_by_port[dport]:
            if packet['n'] not in [pkt['n'] for pkt in unique_premature_packets_by_port[dport]]:
                unique_premature_packets_by_port[dport].append(packet)

    return unique_premature_packets_by_port

def get_premature_tso_packets_by_port(server_packets_by_port, client_ports, delay_time_sec):
    premature_packets_by_port = get_premature_packets_by_port(server_packets_by_port, client_ports, delay_time_sec)

    premature_tso_packets_by_port = {}

    for dport in client_ports:
        premature_tso_packets_by_port[dport] = []

        for packet in premature_packets_by_port:
            if packet['tso'] > 0:
                premature_tso_packets_by_port[dport].append(packet)

    return premature_tso_packets_by_port

def get_unique_premature_tso_packets_by_port(server_packets_by_port, client_ports, delay_time_sec):
    premature_tso_packets_by_port = get_premature_tso_packets_by_port(server_packets_by_port, client_ports, delay_time_sec)

    unique_premature_tso_packets_by_port = {}

    for dport in client_ports:
        unique_premature_tso_packets_by_port[dport] = []

        for packet in premature_tso_packets_by_port[dport]:
            if packet['n'] not in [pkt['n'] for pkt in unique_premature_tso_packets_by_port[dport]]:
                unique_premature_tso_packets_by_port[dport].append(packet)

    return unique_premature_tso_packets_by_port


def get_filtered_server_packets_by_port(server_packets_by_port, client_ports):
    server_transmissions_by_port = {}

    for dport in client_ports:
        server_transmissions_by_port[dport] = list(filter(lambda p: (p['tso'] < 2), server_packets_by_port[dport]))

    return server_transmissions_by_port


def get_throughput_by_port(server_packets_by_port, client_packets_by_port, client_ports):
    throughput_by_port = {}

    server_transmissions_by_port = get_filtered_server_packets_by_port(server_packets_by_port, client_ports)

    for dport in client_ports:
        throughput_by_port[dport] = 0
        start_time = server_packets_by_port[dport][0]['ts']

        for packet in server_transmissions_by_port[dport]:
            if packet['tso'] < 2:
                throughput_by_port[dport] += len(packet['tcp'].data)

        end_time = -1
        for client_packet in reversed(client_packets_by_port[dport]):
            if client_packet['tcp'].seq == server_packets_by_port[dport][-1]['tcp'].seq:
                end_time = client_packet['ts']

        time = end_time - start_time

        if end_time == -1:
            print("COULD NOT FIND MATCHING LAST CLIENT PACKET")
            assert False

        throughput_by_port[dport] /= time

    return throughput_by_port

# Not used. Used tcp dump instead
def get_goodput_by_port(server_packets_to_client_packets_by_port, client_packets_by_port, client_ports):
    goodput_by_port = {}

    for dport in client_ports:
        goodput_by_port[dport] = 0

        client_packets = client_packets_by_port[dport]

        unique_client_packets = []

        server_packets_to_client_packets = server_packets_to_client_packets_by_port[dport]

        start_time = server_packets_to_client_packets[0]['server']['ts']

        for packet in client_packets:

            if packet['tcp'].seq not in [pkt['tcp'].seq for pkt in unique_client_packets]:
                unique_client_packets.append(packet)
                goodput_by_port[dport] += len(packet['tcp'].data)


        end_time = client_packets[-1]['ts']

        goodput_by_port[dport] = goodput_by_port[dport] / (end_time - start_time)

        print("unique client packets length:", len(unique_client_packets), "total client client packets", len(client_packets))

    return goodput_by_port



def get_client_tso_segment_gaps_by_port(client_tso_packets):
    # Find average time between tso segment reception
    client_tso_segment_gap_by_port = {}

    for dport in client_tso_packets.keys():
        client_tso_segment_gap_by_port[dport] = []

        print(dport)
        for packet_counter, tso_packet in enumerate(client_tso_packets[dport]):

            for i in range(1, len(tso_packet)):
                segment = tso_packet[i]
                prev_segment = tso_packet[i-1]

                time_difference = segment['ts'] - prev_segment['ts']

                client_tso_segment_gap_by_port[dport].append(time_difference)

    return client_tso_segment_gap_by_port

def get_client_all_segment_gaps_by_port(client_packets_by_port):

    # Find time gaps between all received packets

    client_all_segment_gaps_by_port = {}

    for dport in client_packets_by_port.keys():
        client_all_segment_gaps_by_port[dport] = []

        for i in range(1, len(client_packets_by_port[dport])):
            packet = client_packets_by_port[dport][i - 1]
            next_packet = client_packets_by_port[dport][i]

            time_difference = next_packet['ts'] - packet['ts']

            client_all_segment_gaps_by_port[dport].append(time_difference)


    return client_all_segment_gaps_by_port


def get_retransmission_pairs_by_port(server_packets_to_client_packets_by_port, client_ports):
    retransmission_pairs_by_port = {}
    not_retransmission_pairs_by_port = {}

    for dport in client_ports:
        retransmission_pairs_by_port[dport] = []
        not_retransmission_pairs_by_port[dport] = []

        for packet_pair in server_packets_to_client_packets_by_port[dport]:
            is_retransmission = False

            for not_retransmission_pair in not_retransmission_pairs_by_port[dport]:
                if not_retransmission_pair['server']['tcp'].seq == packet_pair['server']['tcp'].seq:
                    is_retransmission = True
                    break

            if is_retransmission:
               retransmission_pairs_by_port[dport].append(packet_pair)
            else:
                not_retransmission_pairs_by_port[dport].append(packet_pair)

            # Tagging packet
            packet_pair['server']['rt'] = is_retransmission
            if packet_pair['client'] is not None:
                packet_pair['client']['rt'] = is_retransmission

    return retransmission_pairs_by_port, not_retransmission_pairs_by_port


def get_spurious_and_not_spurious_retransmissions_by_port(retransmission_pairs_by_port, not_retransmission_pairs_by_port, client_ports):
    spurious = {}
    not_spurious = {}

    for dport in client_ports:
        spurious[dport] = []
        not_spurious[dport] = []

        for packet_pair in not_retransmission_pairs_by_port[dport]:
            for retransmission_pair in retransmission_pairs_by_port[dport]:
                if retransmission_pair['server']['tcp'].seq == packet_pair['server']['tcp'].seq:
                    if packet_pair['client'] is not None:
                        not_spurious[dport].append(retransmission_pair)
                        # Tagging packet
                        retransmission_pair['server']['spurious'] = False
                        if retransmission_pair['client'] is not None:
                            retransmission_pair['client']['spurious'] = False
                    else:
                        spurious[dport].append(retransmission_pair)
                        retransmission_pair['server']['spurious'] = True
                        if retransmission_pair['client'] is not None:
                            retransmission_pair['client']['spurious'] = True

    return spurious, not_spurious

def get_out_of_order_packets_by_port(client_packets_by_port, client_ports):
    out_of_order_packets_by_port = {}
    for dport in client_ports:
        out_of_order_packets_by_port[dport] = []

        for i in range(1, len(client_packets_by_port[dport])):
            packet = client_packets_by_port[dport][i]
            prev_packet = client_packets_by_port[dport][i - 1]

            if packet['tcp'].seq < prev_packet['tcp'].seq:
                out_of_order_packets_by_port[dport].append(packet)

    return out_of_order_packets_by_port


def get_tso_packet_next_packet_gaps_by_port(server_packets_by_port, client_ports):
    gaps_by_port = {}

    for dport in client_ports:
        gaps_by_port[dport] = []

        for i in range(1, len(server_packets_by_port[dport])):
            prev_packet = server_packets_by_port[dport][i - 1]
            packet = server_packets_by_port[dport][i]

            if prev_packet['tso'] > 0 and (prev_packet['n'] < packet['n']):
                time_difference = packet['ts'] - prev_packet['ts']

                gaps_by_port[dport].append(time_difference)

    return gaps_by_port


def get_throughput_per_x(pcaps_per_x):
    throughput_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        throughput_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)
            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            throughput_by_port = get_throughput_by_port(server_packets_by_port, client_packets_by_port, client_ports)

            throughputs = 0
            for dport in client_ports:
                throughputs += throughput_by_port[dport]

            throughput = throughputs / len(client_ports)

            throughput_per_x[x]['runs'].append(throughput)

    for x in pcaps_per_x.keys():
        avg_throughput = 0
        for throughput in throughput_per_x[x]['runs']:
            avg_throughput += throughput

        avg_throughput /= len(throughput_per_x[x]['runs'])
        throughput_per_x[x]['avg'] = avg_throughput

    return throughput_per_x


def get_goodput_per_x(pcaps_per_x):
    goodput_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        goodput_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)
            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)

            goodput_by_port = get_goodput_by_port(server_packets_to_client_packets_by_port, client_packets_by_port, client_ports)

            goodputs = 0
            for dport in client_ports:
                goodputs += goodput_by_port[dport]

            goodput = goodputs / len(client_ports)

            goodput_per_x[x]['runs'].append(goodput)

    for x in pcaps_per_x.keys():
        avg_goodput = 0
        for goodput in goodput_per_x[x]['runs']:
            avg_goodput += goodput

        avg_goodput /= len(goodput_per_x[x]['runs'])
        goodput_per_x[x]['avg'] = avg_goodput

    return goodput_per_x


def get_avg_next_packet_gap_per_todo(pcaps):
    avg_next_packet_gap_per_todo = {}

    run_count = 3

    for todo in pcaps.keys():
        avg_next_packet_gap_per_todo[todo] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps[todo]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps[todo]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            next_packet_gaps_by_port = get_tso_packet_next_packet_gaps_by_port(server_packets_by_port, client_ports)

            all_next_packet_gaps = merge_entries_by_port(next_packet_gaps_by_port)

            next_packet_gap_sum = count_sum(all_next_packet_gaps)
            avg_next_packet_gap = next_packet_gap_sum / len(all_next_packet_gaps)

            avg_next_packet_gap_per_todo[todo]['runs'].append(avg_next_packet_gap)


    # Getting average of runs
    for todo in avg_next_packet_gap_per_todo.keys():
        avg_next_packet_gap = 0
        for gap in avg_next_packet_gap_per_todo[todo]['runs']:
            avg_next_packet_gap += gap

        avg_next_packet_gap /= len(avg_next_packet_gap_per_todo[todo]['runs'])
        avg_next_packet_gap_per_todo[todo]['avg'] = avg_next_packet_gap

        next_packet_gap_factor = avg_next_packet_gap / todo

        avg_next_packet_gap_per_todo[todo]['avg'] = next_packet_gap_factor

    return avg_next_packet_gap_per_todo


def get_all_transmission_gaps_per_port(server_packets_by_port, client_ports):
    transmission_gaps = {}

    for dport in client_ports:
        transmission_gaps[dport] = []

        packet_i = 0
        while packet_i < len(server_packets_by_port[dport]):
            # Finding next Non-TSO packet or first segment in TSO packet
            while (server_packets_by_port[dport][packet_i]['tso'] > 1):
                packet_i += 1

            prev_packet_i = packet_i - 1

            # Finding previous Non-TSO packet or first segment in previous TSO packet
            while (prev_packet_i > 0 and server_packets_by_port[dport][prev_packet_i]['tso'] > 1):
                prev_packet_i -= 1

            # Packet and prev are the same packet: skip
            if prev_packet_i < 0:
                packet_i += 1
                continue

            time_difference = server_packets_by_port[dport][packet_i]['ts'] - server_packets_by_port[dport][prev_packet_i]['ts']

            print("Packet:", server_packets_by_port[dport][packet_i]['n'],
                  server_packets_by_port[dport][packet_i]['tcp'].seq, "tso:", server_packets_by_port[dport][packet_i]['tso'],
                  "Prev Packet:", server_packets_by_port[dport][prev_packet_i]['n'],
                  server_packets_by_port[dport][prev_packet_i]['tcp'].seq, "tso:",
                  server_packets_by_port[dport][prev_packet_i]['tso'],
                  "Difference:", time_difference)

            transmission_gaps[dport].append(time_difference)

            packet_i += 1

    return transmission_gaps

def get_all_segment_transmission_gaps_per_port(server_packets_by_port, client_ports):
    transmission_gaps = {}

    for dport in client_ports:
        transmission_gaps[dport] = []

        packet_i = 0
        for packet_i in range(1, len(server_packets_by_port[dport])):
            packet = server_packets_by_port[dport][packet_i]
            prev_packet = server_packets_by_port[dport][packet_i - 1]

            time_difference = packet['ts'] - prev_packet['ts']

            transmission_gaps[dport].append(time_difference)

    return transmission_gaps



def plot_avg_tso_next_packet_gap_per_todo(pcaps):
    plt.clf()

    for label in pcaps.keys():
        print("FILE:", label)
        pcap = pcaps[label]

        next_packet_gap_per_todo = get_avg_next_packet_gap_per_todo(pcap)

        next_packet_gap_per_todo_x = sorted(list(next_packet_gap_per_todo.keys()))
        next_packet_gap_per_todo_y = []

        for todo in next_packet_gap_per_todo_x:
            next_packet_gap_per_todo_y.append(next_packet_gap_per_todo[todo]['avg'] * 1000000)

        plt.xscale("log")
        plt.plot(next_packet_gap_per_todo_x, next_packet_gap_per_todo_y, label=(label + "(TSO segments)"))

    plt.legend(loc="best")
    plt.savefig("avg_tso_next_packet_gap_per_delay.png")


def plot_avg_tso_next_packet_gap_deviation_per_delay(delay_pcaps, fig_name):
    plt.clf()

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        avg_next_packet_gap_per_delay = get_avg_next_packet_gap_per_todo(delay_pcap)

        avg_next_packet_gap_per_delay_x = sorted(list(avg_next_packet_gap_per_delay.keys()))
        avg_next_packet_gap_per_delay_y = []

        for delay in avg_next_packet_gap_per_delay_x:
            delay_us = delay
            avg_next_packet_gap = avg_next_packet_gap_per_delay[delay]['avg'] * 1000000
            next_packet_gap_deviation = ((avg_next_packet_gap - delay_us) / delay_us) * 100

            print("DESIRED DELAY", delay_us, "AVG DELAY:", avg_next_packet_gap, "Deviation:", next_packet_gap_deviation)

            avg_next_packet_gap_per_delay_y.append(next_packet_gap_deviation)

        plt.plot(avg_next_packet_gap_per_delay_x, avg_next_packet_gap_per_delay_y, label=(label))

    plt.xlabel("NIC's configured inter-packet gap (μs)")
    plt.ylabel("Gap between host's TSO packet and following packet: \ndeviation from NIC's configured inter-packet gap (%)")
    plt.xscale("log")
    plt.legend(loc="best")
    plt.savefig(fig_name)

# FIGURE 9: HOSTS GAP BETWEEN TSO AND NEXT PACKET: DEVIATION FROM NICS CONFIGURED DELAY
plot_avg_tso_next_packet_gap_deviation_per_delay(packet_delay_without_1_pcaps, "avg_tso_next_packet_gap_deviation_per_delay.png")
plot_avg_tso_next_packet_gap_deviation_per_delay(packet_delay_pcaps, "avg_tso_next_packet_gap_deviation_with_1_per_delay.png")


# FIGURE 9: HOSTS GAP BETWEEN TSO AND NEXT PACKET
plot_y_per_x(packet_delay_pcaps, get_avg_next_packet_gap_per_todo, "avg_tso_next_packet_gap_per_delay.png", ylabel="Gap between host's transmission of TSO packet \nand following packet (μs)", xlabel="NIC's configured inter-packet gap (μs)", scale_to_us=True)

def get_reordering_rate_per_delay(pcaps_per_delay):
    reordering_per_delay = {}

    run_count = 3

    for delay in pcaps_per_delay.keys():
        reordering_per_delay[delay] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_delay[delay]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_delay[delay]['client'] + "_" + str(run_counter+1)

            client_packets = read_packets(client_pcap)
            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            out_of_order_packets_by_port = get_out_of_order_packets_by_port(client_packets_by_port, client_ports)

            out_of_order_packets = merge_entries_by_port(out_of_order_packets_by_port)

            out_of_order_packets.sort(key=lambda p: (p['n']))

            received_packet_count = count_total_packets_from_all_ports(client_packets_by_port, client_ports)
            reordered_packet_count = len(out_of_order_packets)

            reorder_rate = (reordered_packet_count / received_packet_count) * 100

            reordering_per_delay[delay]['runs'].append(reorder_rate)

    for delay in pcaps_per_delay.keys():
        avg_reordering_rate = 0
        for gap in reordering_per_delay[delay]['runs']:
            avg_reordering_rate += gap

        avg_reordering_rate /= len(reordering_per_delay[delay]['runs'])
        reordering_per_delay[delay]['avg'] = avg_reordering_rate

        print("AVG REORDERING RATE for flows", delay, avg_reordering_rate)

    return reordering_per_delay


def get_premature_packet_rate_per_x(pcaps_per_x):
    premature_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        premature_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            delay_time_sec = x / 1000000
            premature_packets_by_port = get_unique_premature_packets_by_port(server_packets_by_port, client_ports, delay_time_sec)

            premature_packet_count = count_total_packets_from_all_ports(premature_packets_by_port, client_ports)

            server_transmitted_packets = get_filtered_server_packets_by_port(server_packets_by_port, client_ports)

            transmitted_packet_count = count_total_packets_from_all_ports(server_transmitted_packets, client_ports)

            if (transmitted_packet_count < premature_packet_count):
                print("UNIQUE PREMATURE PACKET COUNT:", premature_packet_count)
                print("TOTAL PACKET COUNT:", transmitted_packet_count)

            reorder_rate = (premature_packet_count / transmitted_packet_count) * 100

            premature_rate_per_x[x]['runs'].append(reorder_rate)

    for x in pcaps_per_x.keys():
        avg_premature_rate = 0
        for premature_rate in premature_rate_per_x[x]['runs']:
            avg_premature_rate += premature_rate

        avg_premature_rate /= len(premature_rate_per_x[x]['runs'])
        premature_rate_per_x[x]['avg'] = avg_premature_rate

    return premature_rate_per_x


def get_rt_reordering_rate_per_delay(pcaps_per_delay):
    rt_reordering_per_delay = {}

    run_count = 3

    for delay in pcaps_per_delay.keys():
        rt_reordering_per_delay[delay] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_delay[delay]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_delay[delay]['client'] + "_" + str(run_counter+1)

            client_packets = read_packets(client_pcap)
            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port,
                                                                                            client_packets_by_port,
                                                                                            client_ports)

            get_retransmission_pairs_by_port(server_packets_to_client_packets_by_port, client_ports)

            out_of_order_packets_by_port = get_out_of_order_packets_by_port(client_packets_by_port, client_ports)

            out_of_order_packets = merge_entries_by_port(out_of_order_packets_by_port)

            out_of_order_packets.sort(key=lambda p: (p['n']))

            rt_out_of_order_packets = list(filter(lambda p: (p['rt']), out_of_order_packets))

            reordered_packet_count = len(out_of_order_packets)

            rt_reorder_rate = (len(rt_out_of_order_packets) / reordered_packet_count) * 100

            rt_reordering_per_delay[delay]['runs'].append(rt_reorder_rate)

    for x in pcaps_per_delay.keys():
        avg_rt_reordering_rate = 0
        for rt_reordering in rt_reordering_per_delay[x]['runs']:
            avg_rt_reordering_rate += rt_reordering

        avg_rt_reordering_rate /= len(rt_reordering_per_delay[x]['runs'])
        rt_reordering_per_delay[x]['avg'] = avg_rt_reordering_rate

    return rt_reordering_per_delay

def plot_rt_reordering_per_delay(delay_pcaps):
    plt.clf()
    plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.3f%%'))

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        reordering_rate_per_delay = get_rt_reordering_rate_per_delay(delay_pcap)

        reordering_rate_per_delay_x = sorted(list(reordering_rate_per_delay.keys()))
        reordering_rate_per_delay_y = []

        for delay in reordering_rate_per_delay_x:
            reordering_rate_per_delay_y.append(reordering_rate_per_delay[delay]['avg'])

        plt.plot(reordering_rate_per_delay_x, reordering_rate_per_delay_y, label=(label + "(TSO segments)"))

    plt.legend(loc="best")
    plt.savefig("rt_reordering_per_delay.png")


def plot_premature_rate_per_delay(delay_pcaps, figname):
    plt.clf()
    plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.3f%%'))

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        premature_rate_per_delay = get_premature_packet_rate_per_x(delay_pcap)

        premature_rate_per_delay_x = sorted(list(premature_rate_per_delay.keys()))
        premature_rate_per_delay_y = []

        for delay in premature_rate_per_delay_x:
            premature_rate_per_delay_y.append(premature_rate_per_delay[delay]['avg'])

        plt.xscale("log")
        plt.plot(premature_rate_per_delay_x, premature_rate_per_delay_y, label=label)

    plt.legend(loc="best")
    plt.savefig(figname)


def plot_reordering_per_delay(delay_pcaps):
    plt.clf()

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        reordering_rate_per_delay = get_reordering_rate_per_delay(delay_pcap)

        reordering_rate_per_delay_x = sorted(list(reordering_rate_per_delay.keys()))
        reordering_rate_per_delay_y = []

        for delay in reordering_rate_per_delay_x:
            reordering_rate_per_delay_y.append(reordering_rate_per_delay[delay]['avg'])

        plt.xscale("log")
        plt.plot(reordering_rate_per_delay_x, reordering_rate_per_delay_y, label=(label + "(TSO segments)"))

    plt.ylabel("Packets delivered out of order (%)")
    plt.xlabel("Configured inter-packet gap (μs)")
    plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))
    plt.legend(loc="best")
    plt.savefig("reordering_per_delay.png")



# FIGURE 10: Reordering rate per delay
plot_reordering_per_delay(packet_delay_pcaps)

# plot_y_per_x(flows_0001ms_pcaps, get_reordering_rate_per_delay, "reordering_per_flows.png")

def get_first_second_tso_segment_gaps_by_port(server_packets_to_client_packets_by_port, client_ports):
    first_second_tso_segment_gaps_by_port = {}

    for dport in client_ports:
        first_second_tso_segment_gaps_by_port[dport] = []

        for packet_pair_i in range(1, len(server_packets_to_client_packets_by_port[dport])):
            packet_pair = server_packets_to_client_packets_by_port[dport][packet_pair_i]
            prev_packet_pair = server_packets_to_client_packets_by_port[dport][packet_pair_i - 1]

            # First and second packet
            if (prev_packet_pair['server']['tso'] == 1) and (packet_pair['server']['tso'] == 2):
                # Both packets were received
                if (prev_packet_pair['client'] is not None) and (packet_pair['client'] is not None):
                    time_gap = packet_pair['client']['ts'] - prev_packet_pair['client']['ts']
                    first_second_tso_segment_gaps_by_port[dport].append(time_gap)

                    print("First second tso time gap:", time_gap)

    return first_second_tso_segment_gaps_by_port


def get_avg_first_second_tso_segment_gaps_per_x(pcaps_per_x):
    first_second_gaps_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        first_second_gaps_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)

            first_second_gaps_by_port = get_first_second_tso_segment_gaps_by_port(server_packets_to_client_packets_by_port, client_ports)

            first_second_gaps = merge_entries_by_port(first_second_gaps_by_port)

            total_first_second_gaps = count_sum(first_second_gaps)

            avg_first_second_gap = total_first_second_gaps / len(first_second_gaps)

            first_second_gaps_per_x[x]['runs'].append(avg_first_second_gap)

    # Getting average of runs
    for x in first_second_gaps_per_x.keys():
        avg_first_second_gap = 0
        for first_second_gap in first_second_gaps_per_x[x]['runs']:
            avg_first_second_gap += first_second_gap

        avg_first_second_gap /= len(first_second_gaps_per_x[x]['runs'])
        first_second_gaps_per_x[x]['avg'] = avg_first_second_gap

    return first_second_gaps_per_x


def get_tso_gap_per_delay(pcaps_per_delay):
    gap_per_delay = {}

    run_count = 3

    for delay in pcaps_per_delay.keys():
        gap_per_delay[delay] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_delay[delay]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_delay[delay]['client'] + "_" + str(run_counter+1)

            print("SERVER PCAP", server_pcap, "CLIENT PCAP", client_pcap)

            server_packets = read_packets(server_pcap)

            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            print("CLIENT PORTS", client_ports)
            print("CLIENT PACKETS BY PORT", client_packets_by_port.keys())

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            server_packets_to_client_packets = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)

            client_tso_packets = get_client_tso_packets(server_packets_to_client_packets, client_ports)

            client_tso_segment_gaps_by_port = get_client_tso_segment_gaps_by_port(client_tso_packets)

            client_tso_segment_gaps = merge_entries_by_port(client_tso_segment_gaps_by_port)

            run_avg_gap = count_sum(client_tso_segment_gaps) / len(client_tso_segment_gaps)

            gap_per_delay[delay]['runs'].append(run_avg_gap)

    for delay in pcaps_per_delay.keys():
        avg_gap = 0
        for gap in gap_per_delay[delay]['runs']:
            avg_gap += gap

        avg_gap /= len(gap_per_delay[delay]['runs'])
        gap_per_delay[delay]['avg'] = avg_gap

    return gap_per_delay


def get_all_segment_gap_per_delay(pcaps_per_delay):
    gap_per_delay = {}

    run_count = 3

    for delay in pcaps_per_delay.keys():
        gap_per_delay[delay] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_delay[delay]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_delay[delay]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            client_all_segment_gaps_by_port = get_client_all_segment_gaps_by_port(client_packets_by_port)

            client_all_segment_gaps = merge_entries_by_port(client_all_segment_gaps_by_port)

            run_avg_gap = count_sum(client_all_segment_gaps) / len(client_all_segment_gaps)

            gap_per_delay[delay]['runs'].append(run_avg_gap)

    for delay in pcaps_per_delay.keys():
        avg_gap = 0
        for gap in gap_per_delay[delay]['runs']:
            avg_gap += gap

        avg_gap /= len(gap_per_delay[delay]['runs'])
        gap_per_delay[delay]['avg'] = avg_gap

    return gap_per_delay


def get_transmission_gap_per_x(pcaps_per_x):
    gap_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        gap_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            get_all_transmission_gaps_per_port(server_packets_by_port, client_ports)

            transmission_gaps_by_port = get_all_transmission_gaps_per_port(server_packets_by_port, client_ports)

            all_transmission_gaps = merge_entries_by_port(transmission_gaps_by_port)

            run_avg_gap = count_sum(all_transmission_gaps) / len(all_transmission_gaps)

            gap_per_x[x]['runs'].append(run_avg_gap)

    for x in pcaps_per_x.keys():
        avg_gap = 0
        for gap in gap_per_x[x]['runs']:
            avg_gap += gap

        avg_gap /= len(gap_per_x[x]['runs'])
        gap_per_x[x]['avg'] = avg_gap

    return gap_per_x


def get_segment_transmission_gap_per_x(pcaps_per_x):
    gap_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        gap_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            server_packets = read_packets(server_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)

            transmission_gaps_by_port = get_all_segment_transmission_gaps_per_port(server_packets_by_port, client_ports)

            all_transmission_gaps = merge_entries_by_port(transmission_gaps_by_port)

            run_avg_gap = count_sum(all_transmission_gaps) / len(all_transmission_gaps)

            gap_per_x[x]['runs'].append(run_avg_gap)

    for x in pcaps_per_x.keys():
        avg_gap = 0
        for gap in gap_per_x[x]['runs']:
            avg_gap += gap

        avg_gap /= len(gap_per_x[x]['runs'])
        gap_per_x[x]['avg'] = avg_gap

    return gap_per_x


# FIGURE 7: HOST'S PACING RATE PER DELAY
plot_y_per_x(packet_delay_pcaps, get_segment_transmission_gap_per_x, "segment_transmission_gap_per_delay.png", is_y_log=True, xlabel="NIC's configured inter-packet gap (μs)", ylabel="Host's inter-packet gap (μs)", scale_to_us=True)


def plot_avg_segment_transmission_gap_deviation_per_delay(delay_pcaps, fig_name):
    plt.clf()

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        avg_transmission_gap_per_delay = get_segment_transmission_gap_per_x(delay_pcap)

        avg_transmission_gap_per_delay_x = sorted(list(avg_transmission_gap_per_delay.keys()))
        avg_transmission_gap_per_delay_y = []

        for delay in avg_transmission_gap_per_delay_x:
            delay_us = delay
            avg_next_packet_gap = avg_transmission_gap_per_delay[delay]['avg'] * 1000000
            transmission_gap_deviation = ((avg_next_packet_gap - delay_us) / delay_us) * 100

            avg_transmission_gap_per_delay_y.append(transmission_gap_deviation)

        plt.plot(avg_transmission_gap_per_delay_x, avg_transmission_gap_per_delay_y, label=(label))

    plt.xlabel("NIC's configured inter-packet gap (μs)")
    plt.ylabel("Host's inter-packet gap: \ndeviation from NIC's configured inter-packet gap (%)")
    plt.xscale("log")
    plt.legend(loc="best")
    plt.savefig(fig_name)

# FIGURE 8: HOST'S PACING RATE DEVIATION PER DELAY
plot_avg_segment_transmission_gap_deviation_per_delay(packet_delay_pcaps, "segment_transmission_gap_deviation_per_delay.png")

def plot_gap_per_delay(delay_pcaps, fig_name, gap=None, xlabel="Configured inter-packet gap (μs)", is_x_log=True, is_y_log=True):
    plt.clf()
    # plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1111f% us'))

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        if gap == "tso" or gap is None:
            tso_gap_per_delay = get_tso_gap_per_delay(delay_pcap)

            tso_gap_per_delay_x = sorted(list(tso_gap_per_delay.keys()))
            tso_gap_per_delay_y = []

            for delay in tso_gap_per_delay_x:
                tso_gap_per_delay_y.append(tso_gap_per_delay[delay]['avg'] * 1000000)

            plt.plot(tso_gap_per_delay_x, tso_gap_per_delay_y, label=(label + " (TSO segments)"))

        if gap == "all" or gap is None:
            all_gap_per_delay = get_all_segment_gap_per_delay(delay_pcap)

            all_gap_per_delay_x = sorted(list(all_gap_per_delay.keys()))
            all_gap_per_delay_y = []

            for delay in all_gap_per_delay_x:
                all_gap_per_delay_y.append(all_gap_per_delay[delay]['avg'] * 1000000)

            plt.plot(all_gap_per_delay_x, all_gap_per_delay_y, label=(label + " (All segments)"))


    plt.xlabel(xlabel)
    plt.ylabel("Inter-packet gap (μs)")
    if is_x_log:
        plt.xscale("log")
    if is_y_log:
        plt.yscale("log")
    plt.legend(loc="best")
    plt.savefig(fig_name)


# FIGURE 6: Observed gap per connection entries (pace-all)
plot_gap_per_delay(connection_entries_pcaps, "pace_all_gap_per_entries.png", xlabel="Flow state table capacity", is_y_log=False, is_x_log=False)

# plot_gap_per_delay(flows_pcaps, "gap_per_flows.png")
# plot_gap_per_delay(packet_delay_full_pace_1flow_pcaps, "pace_all_gap_per_delay.png")
# plot_gap_per_delay(packet_delay_tso_pace_1flow_pcaps, "pace_tso_gap_per_delay.png")

def plot_gap_deviation_per_x(delay_pcaps, fig_name, which_gap=None, xlabel="Configured inter-packet gap (μs)", x_unit='%d'):
    plt.clf()
    # plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1111f% us'))

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        delay = -1
        if "1000" in label:
            delay = 1000
        elif "100" in label:
            delay = 100
        elif "10" in label:
            delay = 10
        elif "1" in label:
            delay = 1
        else:
            print("COULD NOT PARSE DELAY FROM LABEL", label)
            assert False

        if which_gap == "tso" or which_gap is None:
            # TSO GAP
            tso_gap_per_delay = get_tso_gap_per_delay(delay_pcap)

            tso_gap_per_delay_x = sorted(list(tso_gap_per_delay.keys()))
            tso_gap_per_delay_y = []

            for x in tso_gap_per_delay_x:
                avg_tso_gap = tso_gap_per_delay[x]['avg'] * 1000000
                tso_gap_deviation = ((avg_tso_gap - delay) / delay) * 100

                tso_gap_per_delay_y.append(tso_gap_deviation)

                print("FLOWS:", x, "DELAY", delay, "AVG DELAY", avg_tso_gap)

            plt.plot(tso_gap_per_delay_x, tso_gap_per_delay_y, label=(label + "(TSO segments)"))

        if which_gap == "all" or which_gap is None:
            # ALL PACKET GAP
            all_gap_per_delay = get_all_segment_gap_per_delay(delay_pcap)

            all_gap_per_delay_x = sorted(list(all_gap_per_delay.keys()))
            all_gap_per_delay_y = []

            for x in all_gap_per_delay_x:
                avg_all_gap = all_gap_per_delay[x]['avg'] * 1000000
                all_gap_deviation = ((avg_all_gap - delay) / delay) * 100

                all_gap_per_delay_y.append(all_gap_deviation)

                print("FLOWS:", x, "DELAY", delay, "AVG DELAY", avg_all_gap)

            plt.plot(all_gap_per_delay_x, all_gap_per_delay_y, label=(label + "(All segments)"))

    plt.gca().yaxis.set_major_formatter(
        mticker.FormatStrFormatter('%d'))
    plt.gca().xaxis.set_major_formatter(mticker.FormatStrFormatter(x_unit))
    plt.xlabel(xlabel)
    plt.ylabel("Deviation from configured gap (%)")
    plt.xticks(tso_gap_per_delay_x)

    plt.legend(loc="best")
    plt.savefig(fig_name)


def plot_gap_deviation_per_delay(delay_pcaps, fig_name, which_gap=None, xlabel="Configured inter-packet gap (μs)", y_unit='%d'):
    plt.clf()

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        if which_gap == "tso" or which_gap is None:

            # TSO GAP
            tso_gap_per_delay = get_tso_gap_per_delay(delay_pcap)

            tso_gap_per_delay_x = sorted(list(tso_gap_per_delay.keys()))
            tso_gap_per_delay_y = []

            for delay in tso_gap_per_delay_x:
                avg_tso_gap = tso_gap_per_delay[delay]['avg'] * 1000000
                tso_gap_deviation = ((avg_tso_gap - delay) / delay) * 100

                tso_gap_per_delay_y.append(tso_gap_deviation)

            plt.xscale("log")
            plt.plot(tso_gap_per_delay_x, tso_gap_per_delay_y, label=(label + " (TSO segments)"))

        if which_gap == "all" or which_gap is None:
            # ALL PACKET GAP
            all_gap_per_delay = get_all_segment_gap_per_delay(delay_pcap)

            all_gap_per_delay_x = sorted(list(all_gap_per_delay.keys()))
            all_gap_per_delay_y = []

            for delay in all_gap_per_delay_x:
                avg_all_gap = all_gap_per_delay[delay]['avg'] * 1000000
                all_gap_deviation = ((avg_all_gap - delay) / delay) * 100

                all_gap_per_delay_y.append(all_gap_deviation)
                print("ALL GAP DEVIATION", all_gap_deviation)

            print(all_gap_per_delay_y)
            plt.xscale("log")

            plt.plot(all_gap_per_delay_x, all_gap_per_delay_y, label=(label + " (All segments)"))

    plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter(y_unit))
    plt.gca().xaxis.set_major_formatter(mticker.FormatStrFormatter('%d'))
    plt.xlabel(xlabel)
    plt.ylabel("Deviation from configured gap (%)")
    plt.xscale("log")

    print("SAVING FIGURE")

    plt.legend(loc="best")
    plt.savefig(fig_name)


# FIGURE 3: Deviation from expected delay
plot_gap_deviation_per_delay(packet_delay_full_pace_1flow_pcaps, fig_name="pace_all_gap_deviation_per_delay.png")
plot_gap_deviation_per_delay(packet_delay_tso_pace_1flow_pcaps, fig_name="pace_tso_gap_deviation_per_delay.png")

# FIGURE 4: Deviation from expected delay (long delay)
plot_gap_deviation_per_delay(long_packet_delay_full_pace_1flow_pcaps, "pace_all_1flow_gap_deviation_per_long_delay.png", y_unit="%0.3f")

# FIGURE 5: Deviation from expected delay (flows)
plot_gap_deviation_per_x(flows_full_pace_pcaps, "pace_all_gap_deviation_per_flows.png", xlabel="Number of parallel TCP flows")
plot_gap_deviation_per_x(flows_tso_pace_pcaps, "pace_tso_gap_deviation_per_flows.png", xlabel="Number of parallel TCP flows", which_gap="tso")


def plot_gap_per_delay_table(delay_pcaps):

    plot_table = {}

    for label in delay_pcaps.keys():
        print("FILE:", label)
        delay_pcap = delay_pcaps[label]

        # TSO GAP
        tso_gap_per_delay = get_tso_gap_per_delay(delay_pcap)

        tso_gap_per_delay_x = sorted(list(tso_gap_per_delay.keys()))
        tso_gap_per_delay_y = []

        plot_table[label] = {}

        for delay in tso_gap_per_delay_x:
            tso_gap_per_delay_y.append(tso_gap_per_delay[delay]['avg'])

            plot_table[label][delay] = {}
            plot_table[label][delay]['tso delay'] = (tso_gap_per_delay[delay]['avg'] * 1000000)
            plot_table[label][delay]['tso deviation'] = ((plot_table[label][delay]['tso delay'] - delay) / delay) * 100

        # ALL PACKET GAP
        all_gap_per_delay = get_all_segment_gap_per_delay(delay_pcap)

        all_gap_per_delay_x = sorted(list(all_gap_per_delay.keys()))
        all_gap_per_delay_y = []

        for delay in all_gap_per_delay_x:
            all_gap_per_delay_y.append(all_gap_per_delay[delay]['avg'])

            plot_table[label][delay]['all delay'] = (all_gap_per_delay[delay]['avg'] * 1000000)
            plot_table[label][delay]['all deviation'] = ((plot_table[label][delay]['all delay'] - delay) / delay) * 100


        # ALL TRANSMISSION GAPS
        tx_gap_per_delay = get_transmission_gap_per_x(delay_pcap)

        tx_gap_per_delay_x = sorted(list(tx_gap_per_delay.keys()))
        tx_gap_per_delay_y = []

        for delay in tx_gap_per_delay_x:
            tx_gap_per_delay_y.append(tx_gap_per_delay[delay]['avg'])

            plot_table[label][delay]['tx delay'] = (tx_gap_per_delay[delay]['avg'] * 1000000)

        seg_tx_gap_per_delay = get_segment_transmission_gap_per_x(delay_pcap)

        seg_tx_gap_per_delay_x = sorted(list(seg_tx_gap_per_delay.keys()))
        seg_tx_gap_per_delay_y = []

        for delay in seg_tx_gap_per_delay_x:
            seg_tx_gap_per_delay_y.append(seg_tx_gap_per_delay[delay]['avg'])

            plot_table[label][delay]['seg tx delay'] = (seg_tx_gap_per_delay[delay]['avg'] * 1000000)


    print("--------------------------------------")
    for label in plot_table.keys():
        print("--------------------------------------")
        print(label)
        for delay in plot_table[label].keys():
            print("FW delay:", delay, "| TSO delay:", plot_table[label][delay]['tso delay'], "| TSO deviation:", str(plot_table[label][delay]['tso deviation']) + "%",
                  "| All delay:", plot_table[label][delay]['all delay'], "| All deviation:", str(plot_table[label][delay]['all deviation']) + "%",
                  "| TX delay:", plot_table[label][delay]['tx delay'], "| Seg TX delay:", plot_table[label][delay]['seg tx delay'])
    print("--------------------------------------")



def get_packet_loss_per_x(pcaps_per_queue_length):
    loss_rate_per_queue_length = {}

    run_count = 3

    for queue_length in pcaps_per_queue_length.keys():
        loss_rate_per_queue_length[queue_length] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_queue_length[queue_length]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_queue_length[queue_length]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)


            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port,
                                                                                            client_packets_by_port,
                                                                                            client_ports)
            lost_packets_by_port = get_lost_packets(server_packets_to_client_packets_by_port, client_ports)

            total_lost_packets = count_total_packets_from_all_ports(lost_packets_by_port, client_ports)

            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            loss_rate = (total_lost_packets / total_packets) * 100

            loss_rate_per_queue_length[queue_length]['runs'].append(loss_rate)


    # Getting average of runs
    for queue_length in pcaps_per_queue_length.keys():
        avg_loss_rate = 0
        for loss_rate in loss_rate_per_queue_length[queue_length]['runs']:
            avg_loss_rate += loss_rate

            print("Loss rate for run:", loss_rate)

        avg_loss_rate /= len(loss_rate_per_queue_length[queue_length]['runs'])
        loss_rate_per_queue_length[queue_length]['avg'] = avg_loss_rate

    return loss_rate_per_queue_length


def get_packet_loss_rate_without_mapping_per_x(pcaps_per_queue_length):
    loss_rate_per_queue_length = {}

    run_count = 3

    for queue_length in pcaps_per_queue_length.keys():
        loss_rate_per_queue_length[queue_length] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_queue_length[queue_length]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_queue_length[queue_length]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_retransmitted_packets_by_port = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

            client_retransmitted_packets_by_port = get_client_retransmitted_packets_by_port(client_ports, client_packets_by_port)

            lost_packets_by_port = get_transmitted_multiple_received_once_by_port(server_packets_by_port, server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports, client_packets_by_port)

            total_lost_packets = count_total_packets_from_all_ports(lost_packets_by_port, client_ports)

            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            loss_rate = (total_lost_packets / total_packets) * 100

            loss_rate_per_queue_length[queue_length]['runs'].append(loss_rate)

    # Getting average of runs
    for queue_length in pcaps_per_queue_length.keys():
        avg_loss_rate = 0
        for loss_rate in loss_rate_per_queue_length[queue_length]['runs']:
            avg_loss_rate += loss_rate

            print("Loss rate for run:", loss_rate)

        avg_loss_rate /= len(loss_rate_per_queue_length[queue_length]['runs'])
        loss_rate_per_queue_length[queue_length]['avg'] = avg_loss_rate

    return loss_rate_per_queue_length


def get_packet_loss_without_mapping_per_x(pcaps_per_queue_length):
    loss_per_queue_length = {}

    run_count = 3

    for queue_length in pcaps_per_queue_length.keys():
        loss_per_queue_length[queue_length] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_queue_length[queue_length]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_queue_length[queue_length]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_retransmitted_packets_by_port = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

            client_retransmitted_packets_by_port = get_client_retransmitted_packets_by_port(client_ports, client_packets_by_port)

            lost_packets_by_port = get_transmitted_multiple_received_once_by_port(server_packets_by_port, server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports, client_packets_by_port)

            total_lost_packets = count_total_packets_from_all_ports(lost_packets_by_port, client_ports)

            loss_per_queue_length[queue_length]['runs'].append(total_lost_packets)


    # Getting average of runs
    for queue_length in pcaps_per_queue_length.keys():
        avg_loss = 0
        for loss in loss_per_queue_length[queue_length]['runs']:
            avg_loss += loss

        avg_loss /= len(loss_per_queue_length[queue_length]['runs'])
        loss_per_queue_length[queue_length]['avg'] = avg_loss

    return loss_per_queue_length



def get_spurious_count_without_mapping_by_port(server_packets_by_port, client_packets_by_port, client_ports):
    server_retransmitted_packets_by_port = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

    client_retransmitted_packets_by_port = get_client_retransmitted_packets_by_port(client_ports, client_packets_by_port)

    lost_packets_by_port = get_transmitted_multiple_received_once_by_port(server_packets_by_port, server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports, client_packets_by_port)

    spurious_count_by_port = {}

    for dport in client_ports:
        loss_count = len(lost_packets_by_port[dport])
        rt_count = len(server_retransmitted_packets_by_port[dport])
        spurious_count_by_port[dport] = rt_count - loss_count

    return spurious_count_by_port

def get_spurious_count_without_mapping_per_x(pcaps):
    spurious_count_per_x = {}

    run_count = 3

    for x in pcaps.keys():
        spurious_count_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            spurious_count_by_port = get_spurious_count_without_mapping_by_port(server_packets_by_port, client_packets_by_port, client_ports)

            spurious_count = 0
            for dport in client_ports:
                spurious_count += spurious_count_by_port[dport]

            spurious_count_per_x[x]['runs'].append(spurious_count)

            assert spurious_count >= 0


    # Getting average of runs
    for x in pcaps.keys():
        avg_count = 0
        for count in spurious_count_per_x[x]['runs']:
            avg_count += count

        avg_count /= len(spurious_count_per_x[x]['runs'])
        spurious_count_per_x[x]['avg'] = avg_count

    return spurious_count_per_x


# FIGURE 14: Spurious count per delay
plot_y_per_x(packet_delay_pcaps, get_spurious_count_without_mapping_per_x, "spurious_count_without_tso_mapping_per_delay.png", xlabel="Configured inter-packet gap (μs)", ylabel="Number of spurious retransmissions", scale_to_us=False)

# FIGURE 12: Loss rate
plot_y_per_x(packet_delay_pcaps, get_packet_loss_rate_without_mapping_per_x, "loss_rate_without_tso_mapping_per_delay.png", xlabel="Configured inter-packet gap (μs)", ylabel="Packet loss rate (%)", is_y_log=False, is_x_log=True, scale_to_us=False)

# FIGURE 12: Loss count
plot_y_per_x(packet_delay_pcaps, get_packet_loss_rate_without_mapping_per_x, "loss_count_without_tso_mapping_per_delay.png", xlabel="Configured inter-packet gap (μs)", ylabel="Number of lost packets", is_y_log=False, is_x_log=True, scale_to_us=False)


# FIGURE 13: Loss rate per queue length
plot_y_per_x(packet_queue_length_pcaps, get_packet_loss_rate_without_mapping_per_x, "loss_rate_without_tso_mapping_per_queue_length.png", is_x_log=False, xlabel="Packet queue capacity", ylabel="Packet loss rate (%)", is_y_log=False, scale_to_us=False)

# plot_y_per_x(packet_delay_pcaps, get_packet_loss_without_mapping_per_x, "loss_count_without_tso_mapping_per_delay.png")
# plot_y_per_x(packet_queue_length_pcaps, get_packet_loss_without_mapping_per_x, "loss_count_without_tso_mapping_per_queue_length.png", is_x_log=False)


def get_spurious_rt_rate_per_todo_old(pcaps):
    spurious_rt_rate_per_todo = {}

    run_count = 3

    for todo in pcaps.keys():
        spurious_rt_rate_per_todo[todo] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps[todo]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps[todo]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_retransmitted_packets_by_port = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

            client_retransmitted_packets_by_port = get_client_retransmitted_packets_by_port(client_ports, client_packets_by_port)

            spurious_transmissions_per_port = get_spurious_retransmissions_by_port(server_retransmitted_packets_by_port, client_retransmitted_packets_by_port, client_ports)

            total_spurious_packets = count_total_packets_from_all_ports(spurious_transmissions_per_port, client_ports)
            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            loss_rate = (total_spurious_packets / total_packets) * 100

            spurious_rt_rate_per_todo[todo]['runs'].append(loss_rate)

    # Getting average of runs
    for queue_length in spurious_rt_rate_per_todo.keys():
        avg_spurious_rate = 0
        for spurious_rate in spurious_rt_rate_per_todo[queue_length]['runs']:
            avg_spurious_rate += spurious_rate

        avg_spurious_rate /= len(spurious_rt_rate_per_todo[queue_length]['runs'])
        spurious_rt_rate_per_todo[queue_length]['avg'] = avg_spurious_rate

    return spurious_rt_rate_per_todo

def get_spurious_rt_rate_per_x(pcaps_per_x):
    spurious_rt_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        spurious_rt_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)
            retransmission_pairs_by_port, not_retransmission_pairs_by_port = get_retransmission_pairs_by_port(server_packets_to_client_packets_by_port, client_ports)

            spurious_transmissions_per_port, not_spurious_transmissions_per_port = get_spurious_and_not_spurious_retransmissions_by_port(retransmission_pairs_by_port, not_retransmission_pairs_by_port, client_ports)

            total_spurious_packets = count_total_packets_from_all_ports(spurious_transmissions_per_port, client_ports)
            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            spurious_rate = (total_spurious_packets / total_packets) * 100

            spurious_rt_rate_per_x[x]['runs'].append(spurious_rate)

    # Getting average of runs
    for x in spurious_rt_rate_per_x.keys():
        avg_spurious_rate = 0
        for spurious_rate in spurious_rt_rate_per_x[x]['runs']:
            avg_spurious_rate += spurious_rate

        avg_spurious_rate /= len(spurious_rt_rate_per_x[x]['runs'])
        spurious_rt_rate_per_x[x]['avg'] = avg_spurious_rate

    return spurious_rt_rate_per_x

def get_not_spurious_rt_rate_per_x(pcaps_per_x):
    not_spurious_rt_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        not_spurious_rt_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)
            retransmission_pairs_by_port, not_retransmission_pairs_by_port = get_retransmission_pairs_by_port(server_packets_to_client_packets_by_port, client_ports)

            spurious_transmissions_per_port, not_spurious_transmissions_per_port = get_spurious_and_not_spurious_retransmissions_by_port(retransmission_pairs_by_port, not_retransmission_pairs_by_port, client_ports)

            total_not_spurious_packets = count_total_packets_from_all_ports(not_spurious_transmissions_per_port, client_ports)
            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            not_spurious_rate = (total_not_spurious_packets / total_packets) * 100

            not_spurious_rt_rate_per_x[x]['runs'].append(not_spurious_rate)

    # Getting average of runs
    for x in not_spurious_rt_rate_per_x.keys():
        avg_not_spurious_rate = 0
        for not_spurious_rate in not_spurious_rt_rate_per_x[x]['runs']:
            avg_not_spurious_rate += not_spurious_rate

        avg_not_spurious_rate /= len(not_spurious_rt_rate_per_x[x]['runs'])
        not_spurious_rt_rate_per_x[x]['avg'] = avg_not_spurious_rate

    return not_spurious_rt_rate_per_x


def plot_not_spurious_rate(pcaps):
    plt.clf()

    for label in pcaps:
        pcap = pcaps[label]

        not_spurious_rate_per_todo = get_not_spurious_rt_rate_per_x(pcap)

        not_spurious_rate_per_todo_x = sorted(list(not_spurious_rate_per_todo.keys()))
        not_spurious_rate_per_todo_y = []

        for queue_length in not_spurious_rate_per_todo_x:
            not_spurious_rate_per_todo_y.append(not_spurious_rate_per_todo[queue_length]['avg'])

        plt.xscale("log")
        plt.plot(not_spurious_rate_per_todo_x, not_spurious_rate_per_todo_y, label=label)

    plt.legend(loc="best")
    plt.savefig("not_spurious_rate_per_delay.png")


def get_rt_rate_per_x(pcaps_per_x):
    rt_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        rt_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port, client_packets_by_port, client_ports)
            retransmission_pairs_by_port, not_retransmission_pairs_by_port = get_retransmission_pairs_by_port(server_packets_to_client_packets_by_port, client_ports)

            total_rt_packets = count_total_packets_from_all_ports(retransmission_pairs_by_port, client_ports)
            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            rt_rate = (total_rt_packets / total_packets) * 100

            rt_rate_per_x[x]['runs'].append(rt_rate)

    # Getting average of runs
    for x in rt_rate_per_x.keys():
        avg_rt_rate = 0
        for rt_rate in rt_rate_per_x[x]['runs']:
            avg_rt_rate += rt_rate

        avg_rt_rate /= len(rt_rate_per_x[x]['runs'])
        rt_rate_per_x[x]['avg'] = avg_rt_rate

    return rt_rate_per_x


def get_rt_rate_without_mapping_per_x(pcaps_per_x):
    rt_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        rt_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            # client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            retransmitted_packets = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

            total_rt_packets = count_total_packets_from_all_ports(retransmitted_packets, client_ports)
            total_packets = count_total_packets_from_all_ports(server_packets_by_port, client_ports)

            rt_rate = (total_rt_packets / total_packets) * 100

            rt_rate_per_x[x]['runs'].append(rt_rate)

    # Getting average of runs
    for x in rt_rate_per_x.keys():
        avg_rt_rate = 0
        for rt_rate in rt_rate_per_x[x]['runs']:
            avg_rt_rate += rt_rate

        avg_rt_rate /= len(rt_rate_per_x[x]['runs'])
        rt_rate_per_x[x]['avg'] = avg_rt_rate


    return rt_rate_per_x


def get_rt_count_without_mapping_per_x(pcaps_per_x):
    rt_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        rt_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter+1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter+1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            # client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            retransmitted_packets = get_server_retransmitted_packets_by_port(server_packets_by_port, client_ports)

            total_rt_packets = count_total_packets_from_all_ports(retransmitted_packets, client_ports)

            rt_rate_per_x[x]['runs'].append(total_rt_packets)

    # Getting average of runs
    for x in rt_rate_per_x.keys():
        avg_rt_rate = 0
        for rt_rate in rt_rate_per_x[x]['runs']:
            avg_rt_rate += rt_rate

        avg_rt_rate /= len(rt_rate_per_x[x]['runs'])
        rt_rate_per_x[x]['avg'] = avg_rt_rate

    return rt_rate_per_x


def plot_rt_rate(pcaps):
    plt.clf()

    for label in pcaps:
        pcap = pcaps[label]

        rt_rate_per_todo = get_rt_rate_per_x(pcap)

        rt_rate_per_todo_x = sorted(list(rt_rate_per_todo.keys()))
        rt_rate_per_todo_y = []

        for queue_length in rt_rate_per_todo_x:
            rt_rate_per_todo_y.append(rt_rate_per_todo[queue_length]['avg'])

        plt.xscale("log")
        plt.plot(rt_rate_per_todo_x, rt_rate_per_todo_y, label=label)

    plt.legend(loc="best")
    plt.savefig("rt_rate_per_queue_length.png")


# FIGURE 1/2: GAPS PER DELAY
plot_y_per_x(packet_delay_tso_pace_1flow_pcaps, get_tso_gap_per_delay, fig_name="", clear_plot=True, save_fig=False, label_suffix=" (TSO segments)", is_y_log=True, xlabel="Configured inter-packet gap (μs)", ylabel="Inter-packet gap (μs)", scale_to_us=True)
plot_y_per_x(packet_delay_tso_pace_1flow_pcaps, get_all_segment_gap_per_delay, fig_name="pace_tso_all_gap_tso_gap_per_delay.png", clear_plot=False, save_fig=True, label_suffix=" (All segments)", is_y_log=True, xlabel="Configured inter-packet gap (μs)", ylabel="Inter-packet gap (μs)", scale_to_us=True)

plot_y_per_x(packet_delay_full_pace_1flow_pcaps, get_tso_gap_per_delay, fig_name="", clear_plot=True, save_fig=False, label_suffix=" (TSO segments)", is_y_log=True, xlabel="Configured inter-packet gap (μs)", ylabel="Avg. inter-packet gap (μs)", scale_to_us=True)
plot_y_per_x(packet_delay_full_pace_1flow_pcaps, get_all_segment_gap_per_delay, fig_name="pace_all_all_gap_tso_gap_per_delay.png", clear_plot=False, save_fig=True, label_suffix=" (All segments)", is_y_log=True, xlabel="Configured inter-packet gap (μs)", ylabel="Inter-packet gap (μs)", scale_to_us=True)
#-----

# FIGURE 11: RETRANSMISSION RATE
plot_y_per_x(packet_delay_pcaps, get_rt_rate_without_mapping_per_x, fig_name="rt_rate_without_tso_mapping_per_delay.png", xlabel="Configured inter-packet gap (μs)", ylabel="Retransmission rate (%)", is_y_log=False, is_x_log=True, scale_to_us=False)

# FIGURE 11: RETRANSMISSION COUNT
plot_y_per_x(packet_delay_pcaps, get_rt_count_without_mapping_per_x, fig_name="rt_count_without_tso_mapping_per_delay.png", xlabel="Configured inter-packet gap (μs)", ylabel="Retransmission count", is_y_log=False, is_x_log=True, scale_to_us=False)


def plot_loss_rate_per_queue_length(packet_queue_length_pcaps):
    plt.clf()
    plt.gca().yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))

    for label in packet_queue_length_pcaps.keys():
        print("FILE:", label)

        packet_queue_length_pcap = packet_queue_length_pcaps[label]

        loss_rate_per_queue_length = get_packet_loss_per_x(packet_queue_length_pcap)

        loss_rate_per_queue_length_x = sorted(list(loss_rate_per_queue_length.keys()))
        loss_rate_per_queue_length_y = []

        for queue_length in loss_rate_per_queue_length_x:
            loss_rate_per_queue_length_y.append(loss_rate_per_queue_length[queue_length]['avg'])

        plt.xscale("log")
        plt.plot(loss_rate_per_queue_length_x, loss_rate_per_queue_length_y, label=label)

    plt.legend(loc="best")
    plt.savefig("loss_rate_per_queue_length.png")


def plot_spurious_rate(pcaps):
    plt.clf()

    for label in pcaps:
        pcap = pcaps[label]

        spurious_rate_per_todo = get_spurious_rt_rate_per_todo_old(pcap)

        spurious_rate_per_todo = get_spurious_rt_rate_per_x(pcap)

        spurious_rate_per_todo_x = sorted(list(spurious_rate_per_todo.keys()))
        spurious_rate_per_todo_y = []

        for queue_length in spurious_rate_per_todo_x:
            spurious_rate_per_todo_y.append(spurious_rate_per_todo[queue_length]['avg'])

        plt.xscale("log")
        plt.plot(spurious_rate_per_todo_x, spurious_rate_per_todo_y, label=label)

    plt.legend(loc="best")
    plt.savefig("spurious_rate_per_delay.png")


def get_tso_packet_interleaving_count(client_tso_packets, client_ports):
    interleaved_segment_count = 0
    interleaved_tso_packet_count = 0
    not_interleaved_tso_packet_count = 0
    not_interleaved_tso_packet_info = []

    for dport in client_ports:
        for tso_packet in client_tso_packets[dport]:
            interleaved_segments = 0

            if len(tso_packet) < 2:
                continue

            first_segment_n = tso_packet[0]['n']
            last_segment_n = tso_packet[-1]['n']

            for other_dport in client_ports:
                for other_tso_packet in client_tso_packets[other_dport]:
                    if other_dport == dport:
                        continue

                    for other_segment in other_tso_packet:
                        if (other_segment['n'] > first_segment_n) and (other_segment['n'] < last_segment_n):
                            interleaved_segments += 1

            interleaved_segment_count += interleaved_segments
            if interleaved_segments > 0:
                interleaved_tso_packet_count += 1
            else:
                not_interleaved_tso_packet_count += 1
                not_interleaved_tso_packet_info.append([first_segment_n, last_segment_n])

    return interleaved_tso_packet_count

def get_tso_packet_interleaving_rate_per_x(pcaps_per_x):
    interleaving_rate_per_x = {}

    run_count = 3

    for x in pcaps_per_x.keys():
        interleaving_rate_per_x[x] = {'avg': -100, 'runs': []}

        for run_counter in range(0, run_count):
            server_pcap = pcaps_per_x[x]['server'] + "_" + str(run_counter + 1) + ".pcap"
            client_pcap = pcaps_per_x[x]['client'] + "_" + str(run_counter + 1)

            print("PCAPS:", server_pcap, client_pcap)

            server_packets = read_packets(server_pcap)
            client_packets = read_packets(client_pcap)

            client_ports = get_client_ports(server_packets)

            server_packets_by_port = get_server_packets_by_port(server_packets, client_ports)
            client_packets_by_port = get_client_packets_by_port(client_packets, client_ports)

            server_packets_to_client_packets_by_port = map_server_packets_to_client_packets(server_packets_by_port,
                                                                                            client_packets_by_port,
                                                                                            client_ports)

            client_tso_packets = get_client_tso_packets(server_packets_to_client_packets_by_port, client_ports)

            get_tso_packet_interleaving_count(client_tso_packets, client_ports)

            total_interleaved_packets = count_total_packets_from_all_ports(client_tso_packets, client_ports)

            total_packets = count_total_packets_from_all_ports(client_tso_packets, client_ports)

            interleaving_rate = (total_interleaved_packets / total_packets) * 100

            interleaving_rate_per_x[x]['runs'].append(interleaving_rate)

    # Getting average of runs
    for x in pcaps_per_x.keys():
        avg_interleaving_rate = 0
        for interleaving_rate in interleaving_rate_per_x[x]['runs']:
            avg_interleaving_rate += interleaving_rate

            print("Interleaving rate for run:", interleaving_rate)

        avg_interleaving_rate /= len(interleaving_rate_per_x[x]['runs'])
        interleaving_rate_per_x[x]['avg'] = avg_interleaving_rate

    return interleaving_rate_per_x


def get_tso_segment_interleaving_rate(client_tso_packets, client_ports):
    # Find interleaving (Two consecutive tso segments are interleaved with other flows' TSO packets)
    interleaved_segment_count = 0
    interleaved_tso_packet_count = 0

    potential_interleaved_segments = 0
    interleaved_segments_out_of_potential = 0

    for dport in client_tso_packets.keys():
        for tso_packet in client_tso_packets[dport]:
            interleaved_segments = 0

            if len(tso_packet) < 2:
                continue

            for i in range(1, len(tso_packet)):
                segment_n = tso_packet[i - 1]['n']
                next_segment_n = tso_packet[i]['n']

                potential_interleaved_segments += 1
                found_interleaving = 0

                for other_dport in client_tso_packets.keys():
                    for other_tso_packet in client_tso_packets[other_dport]:
                        if other_dport == dport:
                            continue

                        for other_segment in other_tso_packet:
                            if (other_segment['n'] > segment_n) and (other_segment['n'] < next_segment_n):
                                interleaved_segments += 1
                                found_interleaving = 1

                if found_interleaving:
                    interleaved_segments_out_of_potential += 1

            interleaved_segment_count += interleaved_segments
            if interleaved_segments > 0:
                interleaved_tso_packet_count += 1