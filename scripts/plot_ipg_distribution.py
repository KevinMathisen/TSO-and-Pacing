import re
import numpy as np
import matplotlib.pyplot as plt

INPUT = """
0x0000000000:  0x00050049 0x00040023 0x0009007b 0x000800ac
0x0000000010:  0x000d00a2 0x00060085 0x000800b1 0x000d00c3
0x0000000020:  0x000300b7 0x0004008a 0x000400d9 0x000400a9
0x0000000030:  0x000300ab 0x000300e8 0x000200b4 0x000200e8
0x0000000040:  0x000800ad 0x000100e2 0x000100a8 0x000100f1
0x0000000050:  0x00140066 0x000e00bd 0x001200a4 0x001800b7
0x0000000060:  0x00050095 0x00020093 0x000e007e 0x001800b9
0x0000000070:  0x00070091 0x00040090 0x000b00b3 0x001800b2
0x0000000080:  0x000a0096 0x00040097 0x000600a4 0x001800a0
0x0000000090:  0x000d0093 0x00050096 0x00030098 0x00180094
0x00000000a0:  0x0010008e 0x00030090 0x00110090 0x00180090
0x00000000b0:  0x00050089 0x00140085 0x00170080 0x0002007f
0x00000000c0:  0x0016007c 0x00180076 0x00170075 0x00150073
0x00000000d0:  0x00030073 0x0018006e 0x0012006e 0x00060091
0x00000000e0:  0x0017006f 0x00100099 0x0009006a 0x00180091
0x00000000f0:  0x000d0086 0x000b0090 0x0018007f 0x000b0060
0x0000000100:  0x000e007d 0x0018005d 0x00080085 0x0010005a
0x0000000110:  0x00180080 0x0005007f 0x0013007e 0x0017007b
0x0000000120:  0x00030056 0x0016007c 0x00180056 0x0017007b
0x0000000130:  0x00170056 0x0016005f 0x00030058 0x0018005d
0x0000000140:  0x0014007e 0x0005005d 0x0017007e 0x00110072
0x0000000150:  0x00080080 0x00180072 0x000e0057 0x000a0074
0x0000000160:  0x00180056 0x000c007f 0x000d0058 0x0018007d
0x0000000170:  0x0009007c 0x0010007f 0x0018007c 0x00070057
0x0000000180:  0x0012007f 0x00170055 0x0004005e 0x00150057
"""

def main():
    # find all 32 bit hex numbers
    values_hex = re.findall(r'0x[0-9a-f]{8}\b', INPUT)

    # convert to base 10
    ipgs_raw = [int(value[6:], 16) for value in values_hex]
    pkt_cnt_raw = [int(value[:6], 16) for value in values_hex]

    # print out overview
    print(f"IPG stats: {len(ipgs_raw)} values, {min(ipgs_raw)} min, {max(ipgs_raw)} max, {sum(ipgs_raw)/len(ipgs_raw):.2f} average")
    print(f"Packet count stats: {len(pkt_cnt_raw)} values, {min(pkt_cnt_raw)} min, {max(pkt_cnt_raw)} max, {sum(pkt_cnt_raw)/len(pkt_cnt_raw):.2f} average")

    # ====== CDF of IPG =======
    ipgs_array = np.asarray(ipgs_raw, dtype=float)
    
    ipgs = ipgs_array / 10 # 100ns to us
    ipgs = np.sort(ipgs)
    cdf_buckets = np.linspace(0.0, 1.0, len(ipgs), endpoint=True)

    fig = plt.figure(figsize=(10, 6))
    plt.plot(ipgs, cdf_buckets, label="CDF")
    plt.xlabel("IPG (us)")
    plt.ylabel("Cumulative prob")
    plt.title("CDF of IPG (us) in Notify")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()
    plt.close(fig)

    # ====== CDF of Packet count =======
    pkt_cnt_array = np.asarray(pkt_cnt_raw, dtype=float)
    
    pkt_cnt = np.sort(pkt_cnt_array)
    cdf_buckets = np.linspace(0.0, 1.0, len(pkt_cnt), endpoint=True)

    fig = plt.figure(figsize=(10, 6))
    plt.plot(pkt_cnt, cdf_buckets, label="CDF")
    plt.xlabel("Packets in burst")
    plt.ylabel("Cumulative prob")
    plt.title("CDF of burst sizes in Notify")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()
    plt.close(fig)

    # ====== Scatter plot of IPG against Packet Count =====

    y_data = ipgs_array / 10 # 100ns to us
    x_data = pkt_cnt_array

    fig = plt.figure(figsize=(10, 6))
    plt.scatter(x_data, y_data, s=20, c='blue', alpha=0.5)
    plt.xlabel("Packets in burst")
    plt.ylabel("IPG of burst (us)")
    plt.title("Scatter plot of IPG compared to burst size")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()
    plt.close(fig)


if __name__ == "__main__":
    main()