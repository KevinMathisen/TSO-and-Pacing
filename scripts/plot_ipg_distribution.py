import re
import numpy as np
import matplotlib.pyplot as plt

INPUT = """
0x0000000000:  0x0000004b 0x00000030 0x00000057 0x000000b2
0x0000000010:  0x0000009a 0x000000bf 0x000000ca 0x000000b0
0x0000000020:  0x00000090 0x00000092 0x000000a8 0x0000009e
0x0000000030:  0x000000a4 0x000000a3 0x000000b2 0x000000c3
0x0000000040:  0x000000a6 0x0000009e 0x00000087 0x000000a0
0x0000000050:  0x00000099 0x00000093 0x00000093 0x0000008e
0x0000000060:  0x0000008a 0x00000093 0x00000089 0x0000008e
0x0000000070:  0x000000af 0x0000007f 0x000000a3 0x00000079
0x0000000080:  0x0000009a 0x00000078 0x00000093 0x00000073
0x0000000090:  0x00000090 0x0000008c 0x0000009b 0x00000089
"""

def main():
    # find all 32 bit hex numbers
    values_hex = re.findall(r'0x[0-9a-f]{8}\b', INPUT)

    # convert to base 10
    values = [int(value, 16) for value in values_hex]

    # print out overview
    print(f"{len(values)} values, {min(values)} min, {max(values)} max, {sum(values)/len(values):.2f} average")

    values_array = np.asarray(values, dtype=float)
    
    # this is for converting numbers from 100ns IPG to us
    ipgs = values_array / 10
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

if __name__ == "__main__":
    main()