def _interval_overlap_and_union(intervals: list[tuple[int, int]], a: int, b: int) -> tuple[int, list[tuple[int, int]]]:
    """
    takes in disjoint, sorted intervals of seq nums and new packet seq [a,b), checks if packet has overlap with intervals,
    and return new existing seq with seq from packet added
    """
    if a >= b:
        return 0, intervals
    overl = 0
    new_a, new_b = a, b
    out = []
    inserted = False
    for (s, e) in intervals:
        if e < new_a:
            out.append((s, e))
            continue
        if s > new_b:
            if not inserted:
                out.append((new_a, new_b))
                inserted = True
            out.append((s, e))
            continue
        # packet seq overlaps with already received:
        overl += max(0, min(e, new_b) - max(s, new_a))
        new_a = min(new_a, s)
        new_b = max(new_b, e)
    if not inserted:
        out.append((new_a, new_b))

    out.sort(key=lambda x: x[0])
    return overl, out

def _detect_retrans_and_ooo(seq: np.ndarray, tcp_len: np.ndarray) -> tuple[int, int, np.ndarray, np.ndarray]:
    """
    Get amount of retransmission and out-of-order packets
      - Retransmission if current [seq, seq+len) overlaps already covered union.
      - Out-of-order if current seq < previous seq (arrival-time view)
    """
    n = seq.size

    retrans_pkts = ooo_pkts = 0
    is_retrans = np.zeros(n, dtype=np.int8)
    is_ooo = np.zeros(n, dtype=np.int8)

    covered = [] # all seq intervals received so far in the transmission
    last_seq = None

    for i in range(n): # for each packet
        s = int(seq[i]), l = int(tcp_len[i])

        if last_seq is not None and s < last_seq:
            ooo_pkts += 1
            is_ooo[i] = 1
        last_seq = s

        if l <= 0: continue # ignore empty packets, may be redundant

        overl, covered = _interval_overlap_and_union(covered, s, s+l)
        if overl > 0: # if some part of this packet has already been covered
            retrans_pkts += 1
            is_retrans[i] = 1

    return retrans_pkts, ooo_pkts, is_retrans, is_ooo