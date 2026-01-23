/*
 * Copyright (C) 2014-2019,  Netronome Systems, Inc.  All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * @file          blocks/vnic/pci_in/notify.c
 * @brief         Code to notify host and app that packet was transmitted
 */

#include <nfp6000/nfp_cls.h>
#include <nfp6000/nfp_me.h>

#include <assert.h>
#include <nfp.h>
#include <nfp_chipres.h>

#include <nfp/me.h>
#include <nfp/mem_ring.h>

#include <vnic/nfd_common.h>
#include <vnic/pci_in.h>
#include <vnic/shared/nfd.h>
#include <vnic/shared/nfd_internal.h>
#include <vnic/utils/ctm_ring.h>
#include <vnic/utils/ordering.h>
#include <vnic/utils/qc.h>
#include <vnic/utils/qcntl.h>
#include <nfp/mem_bulk.h>
#include <std/reg_utils.h>

/* TODO: get NFD_PCIE_ISL_BASE from a common header file */
#define NOTIFY_RING_ISL (PCIE_ISL + 4)

#if !defined(NFD_IN_HAS_ISSUE0) && !defined(NFD_IN_HAS_ISSUE1)
#error "At least one of NFD_IN_HAS_ISSUE0 and NFD_IN_HAS_ISSUE1 must be defined"
#endif

#define LSO_PKT_XFER_START0     16
#define LSO_PKT_XFER_START1     24


struct _issued_pkt_batch {
    struct nfd_in_issued_desc pkt0;
    struct nfd_in_issued_desc pkt1;
    struct nfd_in_issued_desc pkt2;
    struct nfd_in_issued_desc pkt3;
    struct nfd_in_issued_desc pkt4;
    struct nfd_in_issued_desc pkt5;
    struct nfd_in_issued_desc pkt6;
    struct nfd_in_issued_desc pkt7;
};

struct _pkt_desc_batch {
    struct nfd_in_pkt_desc pkt0;
    struct nfd_in_pkt_desc pkt1;
    struct nfd_in_pkt_desc pkt2;
    struct nfd_in_pkt_desc pkt3;
    struct nfd_in_pkt_desc pkt4;
    struct nfd_in_pkt_desc pkt5;
    struct nfd_in_pkt_desc pkt6;
    struct nfd_in_pkt_desc pkt7;
};


NFD_INIT_DONE_DECLARE;

/* Shared with issue DMA */
/* XXX the compl_refl_in xfers are accessed via #defined address
 * this avoids register live range and allocation problems */
__xread unsigned int nfd_in_data_compl_refl_in = 0;
__xread unsigned int nfd_in_jumbo_compl_refl_in = 0;
__remote volatile __xread unsigned int nfd_in_data_served_refl_in;
__remote volatile SIGNAL nfd_in_data_served_refl_sig;


/* Used for issue DMA 0 */
__shared __gpr unsigned int data_dma_seq_served0 = 0;
__shared __gpr unsigned int data_dma_seq_compl0 = 0;

/* Used for issue DMA 1 */
__shared __gpr unsigned int data_dma_seq_served1 = 0;
__shared __gpr unsigned int data_dma_seq_compl1 = 0;


/* Notify private variables */
static __gpr unsigned int data_dma_seq_sent = 0;
static __gpr mem_ring_addr_t lso_ring_addr;
static __gpr unsigned int lso_ring_num;


static SIGNAL wq_sig0, wq_sig1, wq_sig2, wq_sig3;
static SIGNAL wq_sig4, wq_sig5, wq_sig6, wq_sig7;
static SIGNAL msg_sig0, msg_sig1, qc_sig;
static SIGNAL get_order_sig;    /* Signal for reordering before issuing get */
static SIGNAL msg_order_sig;    /* Signal for reordering on message return */
static SIGNAL_MASK wait_msk;
static unsigned int next_ctx;

__xwrite struct _pkt_desc_batch batch_out;

#ifdef NFD_IN_LSO_CNTR_ENABLE
static unsigned int nfd_in_lso_cntr_addr = 0;
#endif


#ifdef NFD_IN_WQ_SHARED

#define NFD_IN_RINGS_MEM_IND2(_isl, _emem)                              \
    _NFP_CHIPRES_ASM(.alloc_mem nfd_in_rings_mem0 _emem global          \
                     (NFD_IN_WQ_SZ * NFD_IN_NUM_WQS)                    \
                     (NFD_IN_WQ_SZ * NFD_IN_NUM_WQS))
#define NFD_IN_RINGS_MEM_IND1(_isl, _emem) NFD_IN_RINGS_MEM_IND2(_isl, _emem)
#define NFD_IN_RINGS_MEM_IND0(_isl)                     \
    NFD_IN_RINGS_MEM_IND1(_isl, NFD_IN_WQ_SHARED)
#define NFD_IN_RINGS_MEM(_isl) NFD_IN_RINGS_MEM_IND0(_isl)

#define NFD_IN_RING_INIT_IND0(_isl, _num)                               \
    NFD_IN_RING_NUM_ALLOC(_isl, _num)                                   \
    _NFP_CHIPRES_ASM(.declare_resource nfd_in_ring_mem_res0##_num       \
                     global NFD_IN_WQ_SZ nfd_in_rings_mem0)             \
    _NFP_CHIPRES_ASM(.alloc_resource nfd_in_ring_mem0##_num             \
                     nfd_in_ring_mem_res0##_num global                  \
                     NFD_IN_WQ_SZ NFD_IN_WQ_SZ)                         \
    _NFP_CHIPRES_ASM(.init_mu_ring nfd_in_ring_num0##_num               \
                     nfd_in_ring_mem0##_num)
#define NFD_IN_RING_INIT(_isl, _num) NFD_IN_RING_INIT_IND0(_isl, _num)

#else /* !NFD_IN_WQ_SHARED */

#define NFD_IN_RINGS_MEM_IND2(_isl, _emem)                              \
    _NFP_CHIPRES_ASM(.alloc_mem nfd_in_rings_mem##_isl _emem global     \
                     (NFD_IN_WQ_SZ * NFD_IN_NUM_WQS)                    \
                     (NFD_IN_WQ_SZ * NFD_IN_NUM_WQS))
#define NFD_IN_RINGS_MEM_IND1(_isl, _emem) NFD_IN_RINGS_MEM_IND2(_isl, _emem)
#define NFD_IN_RINGS_MEM_IND0(_isl)                     \
    NFD_IN_RINGS_MEM_IND1(_isl, NFD_PCIE##_isl##_EMEM)
#define NFD_IN_RINGS_MEM(_isl) NFD_IN_RINGS_MEM_IND0(_isl)

#define NFD_IN_RING_INIT_IND0(_isl, _num)                               \
    NFD_IN_RING_NUM_ALLOC(_isl, _num)                                   \
    _NFP_CHIPRES_ASM(.declare_resource nfd_in_ring_mem_res##_isl##_num  \
                     global NFD_IN_WQ_SZ nfd_in_rings_mem##_isl)        \
    _NFP_CHIPRES_ASM(.alloc_resource nfd_in_ring_mem##_isl##_num        \
                     nfd_in_ring_mem_res##_isl##_num                    \
                     global NFD_IN_WQ_SZ NFD_IN_WQ_SZ)                  \
    _NFP_CHIPRES_ASM(.init_mu_ring nfd_in_ring_num##_isl##_num          \
                     nfd_in_ring_mem##_isl##_num)
#define NFD_IN_RING_INIT(_isl, _num) NFD_IN_RING_INIT_IND0(_isl, _num)

#endif /* NFD_IN_WQ_SHARED */


NFD_IN_RINGS_MEM(PCIE_ISL);

#if NFD_IN_NUM_WQS > 0
    NFD_IN_RING_INIT(PCIE_ISL, 0);
#else
    #error "NFD_IN_NUM_WQS must be a power of 2 between 1 and 8"
#endif

#if NFD_IN_NUM_WQS > 1
    NFD_IN_RING_INIT(PCIE_ISL, 1);
#endif

#if NFD_IN_NUM_WQS > 2
    NFD_IN_RING_INIT(PCIE_ISL, 2);
    NFD_IN_RING_INIT(PCIE_ISL, 3);
#endif

#if NFD_IN_NUM_WQS > 4
    NFD_IN_RING_INIT(PCIE_ISL, 4);
    NFD_IN_RING_INIT(PCIE_ISL, 5);
    NFD_IN_RING_INIT(PCIE_ISL, 6);
    NFD_IN_RING_INIT(PCIE_ISL, 7);
#endif

#if NFD_IN_NUM_WQS > 8
    #error "NFD_IN_NUM_WQS > 8 is not supported"
#endif


static __shared mem_ring_addr_t wq_raddr;
static __shared unsigned int wq_num_base;
static __gpr unsigned int dst_q;



#ifdef NFD_IN_ADD_SEQN

#if (NFD_IN_NUM_SEQRS == 1)
/* Add sequence numbers, using a shared GPR to store */
static __shared __gpr unsigned int dst_q_seqn = 0;

/* No prep required for a single sequencer */
#define NFD_IN_ADD_SEQN_PREP                                            \
do {                                                                    \
} while (0)

#define NFD_IN_ADD_SEQN_PROC                                            \
do {                                                                    \
    pkt_desc_tmp.seq_num = dst_q_seqn;                                  \
    dst_q_seqn++;                                                       \
} while (0)

#else /* (NFD_IN_NUM_SEQRS == 1) */

#define NFD_IN_SEQN_PTR *l$index3

/* Add sequence numbers, using a LM to store */
static __shared __lmem unsigned int seq_nums[NFD_IN_NUM_SEQRS];

#define NFD_IN_ADD_SEQN_PREP                                            \
do {                                                                    \
    local_csr_write(                                                    \
        local_csr_active_lm_addr_3,                                     \
        (uint32_t) &seq_nums[NFD_IN_SEQR_NUM(batch_in.pkt0.__raw[0])]); \
} while (0)

#define NFD_IN_ADD_SEQN_PROC                                            \
do {                                                                    \
    __asm { ld_field[pkt_desc_tmp.__raw[0], 6, NFD_IN_SEQN_PTR, <<8] }  \
    __asm { alu[NFD_IN_SEQN_PTR, NFD_IN_SEQN_PTR, +, 1] }               \
} while (0)

#endif /* (NFD_IN_NUM_SEQRS == 1) */

#else /* NFD_IN_ADD_SEQN */

/* Null sequence number add */
#define NFD_IN_ADD_SEQN_PREP                                            \
do {                                                                    \
} while (0)

#define NFD_IN_ADD_SEQN_PROC                                            \
do {                                                                    \
} while (0)

#endif /* NFD_IN_ADD_SEQN */

#if (NFD_IN_NUM_WQS == 1)
#define _SET_DST_Q(_pkt)                                                \
do {                                                                    \
} while (0)
#else /* (NFD_IN_NUM_WQS == 1) */
#define _SET_DST_Q(_pkt)                                                \
do {                                                                    \
    /* Removing dst_q support for driving pkts to specified wq */       \
} while (0)
#endif /* (NFD_IN_NUM_WQS == 1) */


/* Registers to store reset state */
__xread unsigned int notify_reset_state_xfer = 0;
__shared __gpr unsigned int notify_reset_state_gpr = 0;

/* ========================================================================================*/
/* ------------ k_pace: constants, shared variables, and pacing functions ---------------- */
/* ========================================================================================*/

/* -------------------- k_pace: Debug ------------------------------------------- */
__export __emem uint32_t wire_debug[1024*1024];
__export __emem uint32_t wire_debug_idx;

__shared __gpr uint32_t debug_index = 0; // Offset from wire_debug to append debug info to.

/*
 * Write a 32-bit words to EMEM for debugging, without swapping contexts.
 * Its contents can be read using "nfp-rtsym _wire_debug"
 * (We print 800th to 1000th tso burst)
*/
#define DEBUG(_a) do { \
    if (debug_index < 200) { \
        wait_for_all(&wq_sig7); \
        batch_out.pkt7.__raw[3] = _a; \
        __mem_write32(&batch_out.pkt7.__raw[3], wire_debug + (debug_index), 4, 4, sig_done, &wq_sig7); \
        debug_index += 1; \
    } \
 } while(0)


/* ========================= Pacing Queue and its variables ===============================
 * (1 tick = 20ns)
 *
 *            pq_head_time (time in ticks)
 *                |
 *                |  pq_head (index)
 *                |       | 
 *    0           |       |      PQ_LENGTH - 1 (223)
 *    |           |       |            |
 *  +---+---+-----+------------+-----+---+
 *  | 0 | 1 | ... |     n      | ... | m |    - 224*16B = 3 584 B
 *  +---+---+-----+------------+-----+---+
 * 
 *                |____________|
 *                      |
 *            PQ_SLOT_TICKS (256 ticks = 5.12 us)
 *  |____________________________________|
 *                     |
 *          PQ_HORIZON_TICKS (57 344 ticks = 1.147 ms)    This represents how long in the future we can set packet departures         
 * 
 * 
 * ===================== Calculating Slot/index to insert packet into based on departure time ==================
 * 
 * Departure_time:    0000 0000 0001 1110 0010 0000 0011 1110   1101 0110 1001 1111 0100 1101 1010 1011     (8 479 703 562 143 147)
 *  64 bit                                                    |
 *                                   +--- Subtract by head ---+
 *                                   v
 * Delta_time:        0000 0000 0000 0000 0110 1101 1010 1011       ( 28075 ticks, 561 us in the future)
 *  32 bit                                    |
 *                                            +-shift->-+           ( PQ_TICKS_TO_SLOT_SHIFT = 8 )
 *                                                      |
 * Delta_slots:       0000 0000 0000 0000 0000 0000 0110 1101       ( 109 )
 *  32 bit                               |
 *                        So we can add 109 to pq_head to get
 *                        where we should place the packet.
 * 
 * 
 * ============================== Bitmask =========================================
 *  need 1 bit for each slot -> 224 slots -> 7 x 32 bit
 * 
 *  +------------+------+------------+
 *  | bit_mask_0 |  ... | bit_mask_n |   - 7*4B = 28 B
 *  +------------+------+------------+
 *                            |
 *   bitmask:    0000 0000 0000 0000 1000 0000
 *                                   |
 *                                There is a packet at index "7 + bitmask_num * 32"
*/ 

/* -------- Constants/shared variables (PACING_QUEUE == PQ) -------- */

#define PQ_CTM_LENGTH 4096
#define PQ_LM_LENGTH 192
#define PQ_LM_SYNC_LENGTH 128

#define PQ_SLOT_TICKS 32
#define PQ_HORIZON_TICKS 32*4096

#define PQ_CTM_MASK (PQ_CTM_LENGTH - 1u)
#define PQ_TICKS_TO_SLOT_SHIFT 5u           /* How many bits to shift offset to get slot in queue */

#define PQ_BITMASKS_LENGTH 128
#define LM_BITMASKS_LENGTH 6

#define INDEX_TO_BITMASK_SHIFT 5u           /* each bitmask 32 bits, so need to remove 5 first bits to get bitmask index  */
#define INDEX_IN_BITMASK_MASK 0x0000001F    /* ... and only keep first 5 to get index inside bitmask */

#define PQ_TRESH_FUTURE_SLOTS 3072


#define PQ_CTM_RING_DIFF(_to, _from) (((_to) - (_from)) & PQ_CTM_MASK)


/* CTM Pacing Queue */
__export __ctm40 struct nfd_in_pkt_desc ctm_pacing_queue[PQ_CTM_LENGTH];

__shared __lmem struct nfd_in_pkt_desc lm_pacing_queue[PQ_LM_LENGTH];

__shared __gpr uint32_t pq_ctm_head = 0;
__shared __gpr uint64_t pq_head_time = 0;
__shared __gpr uint32_t pq_ctm_sync_end = 128;

__shared __gpr uint32_t pq_lm_head = 0;
__shared __gpr uint32_t pq_lm_dequeue_cnt = 0;
__shared __gpr uint32_t pq_lm_sync_end = 128;

__gpr uint32_t next_batch_out = 0;

/* k_pace: Bitmask */
__shared __lmem uint32_t bitmasks[PQ_BITMASKS_LENGTH];
__shared __lmem uint32_t lm_bitmasks[LM_BITMASKS_LENGTH];

/* k_pace: FlowID mapping and time */
__shared __lmem uint64_t flows_prev_dep_time[8];

/* --------------------- k_pace utilies ---------------------------------------- */

__intrinsic uint64_t
get_current_time()
{
	return me_tsc_read();
}

__intrinsic void
raise_signal(SIGNAL *sig)
{
    unsigned int val, ctx;
    ctx = ctx();
    val = NFP_MECSR_SAME_ME_SIGNAL_SIG_NO(__signal_number(sig)) |
            NFP_MECSR_SAME_ME_SIGNAL_CTX(ctx);
    local_csr_write(local_csr_same_me_signal, val);
    __implicit_write(sig);
}

#define _BATCH_IN_TO_LM(_pkt)                                               \
do {                                                                        \
    /* TODO: may only copy slots with packet in bitmask */                  \
                                                                            \
    lm_index = old_pq_lm_sync_end+_pkt;                                     \
                                                                            \
    /* If we dont overwrite packet in lm, insert slot to lm */              \
    if (!( (bitmask >> (lm_index & INDEX_IN_BITMASK_MASK)) & 1u )) {        \
        lm_pacing_queue[lm_index] = batch_in.pkt##_pkt##;                   \
    }                                                                       \
                                                                            \
} while (0)

/**
 * Sync 8 slots from CTM to LM if needed
 *
 */
__intrinsic void
sync_ctm_lm() {
    uint32_t bitmask;
    __ctm40 void *ctm_ptr;
    unsigned int old_pq_lm_sync_end, addr_hi, addr_lo, lm_index;

    __xread struct _pkt_desc_batch batch_in;

    /* Need more than 8 slots to sync! */
    if (pq_lm_dequeue_cnt < 8) return;

    // Save where we want to write to in lm
    old_pq_lm_sync_end = pq_lm_sync_end;

    // Issue read from CTM to batch_in
    ctm_ptr = &ctm_pacing_queue[pq_ctm_sync_end];
    addr_hi = ((unsigned long long)ctm_ptr >> 8) & 0xff000000;
    addr_lo = ((unsigned long long)ctm_ptr & 0xffffffff);
    __asm {
        mem[read, batch_in.pkt0, addr_hi, <<8, addr_lo, __ct_const_val(8)], \
                        sig_done[*msg_sig0];
    }
    addr_lo += (4u * sizeof(struct nfd_in_pkt_desc));
    __asm {
        mem[read, batch_in.pkt4, addr_hi, <<8, addr_lo, __ct_const_val(8)], \
                        sig_done[*msg_sig1];
    }

    // Update pointers to "reserve" these 8 slots for us
    pq_lm_dequeue_cnt -= 8;
    pq_lm_sync_end += 8;
    if (pq_lm_sync_end >= PQ_LM_LENGTH) pq_lm_sync_end -= PQ_LM_LENGTH;
    pq_ctm_sync_end += 8;
    if (pq_ctm_sync_end >= PQ_CTM_LENGTH) pq_ctm_sync_end -= PQ_CTM_LENGTH;

    wait_for_all(&msg_sig0, &msg_sig1);

    // Place 8 slots in batch_in to LM
    bitmask = lm_bitmasks[old_pq_lm_sync_end >> INDEX_TO_BITMASK_SHIFT];

    _BATCH_IN_TO_LM(0);
    _BATCH_IN_TO_LM(1);
    _BATCH_IN_TO_LM(2);
    _BATCH_IN_TO_LM(3);
    _BATCH_IN_TO_LM(4);
    _BATCH_IN_TO_LM(5);
    _BATCH_IN_TO_LM(6);
    _BATCH_IN_TO_LM(7);
}

/* ---------------------------- k_pace: Dequeue functions ------------------------------ */
#define _DEQUEUE_PROC(_pkt)                                                 \
do {                                                                        \
    /* Clear signal (it is implied raised if this macro is called )*/       \
    /* (halt if not raised, as this indicates come corruption) */           \
    if (!signal_test(&wq_sig##_pkt)) { DEBUG(0x0001); halt(); }              \
                                                                            \
    raw0_buff = lm_pacing_queue[pq_lm_head].__raw[0];                       \
                                                                            \
    /* Point csr addr 3 (seqn_ptr) to correct queue */                      \
    local_csr_write(local_csr_active_lm_addr_3,                             \
        (uint32_t) &seq_nums[NFD_IN_SEQR_NUM(raw0_buff)]);                  \
                                                                            \
    /* Set seqn of packet, then increase counter */                         \
    __asm { ld_field[raw0_buff, 6, NFD_IN_SEQN_PTR, <<8] }                  \
    __asm { alu[NFD_IN_SEQN_PTR, NFD_IN_SEQN_PTR, +, 1] }                   \
                                                                            \
    batch_out.pkt##_pkt## = lm_pacing_queue[pq_lm_head];                    \
    batch_out.pkt##_pkt##.__raw[0] = raw0_buff;                             \
                                                                            \
    __mem_workq_add_work(dst_q, wq_raddr, &batch_out.pkt##_pkt,             \
                            out_msg_sz_2, out_msg_sz_2, sig_done,           \
                            &wq_sig##_pkt);                                 \
                                                                            \
} while (0)

/**
 * Dequeue up to batch of packets and send to work queue
 *
 */
__intrinsic void
dequeue_pacing_queue() {
    __gpr uint32_t raw0_buff;
    uint64_t now;
    uint32_t index_in_bitmask, bitmask_index, slots_to_send;
    uint32_t out_msg_sz_2 = sizeof(struct nfd_in_pkt_desc);

    /* We are not done until we reach current time (slots_to_send == 0), 
       or have used (all) batch_out */
    while (next_batch_out != 8) {
        
        /* Check if any slots are due for departure */
        now = get_current_time();
        if (now <= pq_head_time) return;
        slots_to_send = (uint32_t)((now-pq_head_time) >> PQ_TICKS_TO_SLOT_SHIFT);
        if (slots_to_send == 0) return;

        /* TODO: we could check if there even is anything at head to send. if not, we can skip wait and move to next head 
                 However this only improved speed at medium to low load, and would negatively affect high loads, aka where we
                 need performance the most. (as at high loads check would always return true) */

        /* Wait until the least recently used batch_out._pkt is available to write
           (this will check if signal raised, but not clear it) */
        switch (next_batch_out) {
            case 0: wait_for_any(&wq_sig0); break;
            case 1: wait_for_any(&wq_sig1); break;
            case 2: wait_for_any(&wq_sig2); break;
            case 3: wait_for_any(&wq_sig3); break;
            case 4: wait_for_any(&wq_sig4); break;
            case 5: wait_for_any(&wq_sig5); break;
            case 6: wait_for_any(&wq_sig6); break;
            case 7: wait_for_any(&wq_sig7); break;
        }

        /* Wait is done, so we can dequeue. Need to check if we should still dequeue 
           (as head and "now" may have been moved while we waited) */
        now = get_current_time();
        if (now <= pq_head_time) return;
        slots_to_send = (uint32_t)((now-pq_head_time) >> PQ_TICKS_TO_SLOT_SHIFT);
        if (slots_to_send == 0) return;

        /* --- We are now checking slot pq_head points to */

        /* Calculate which bitmask to check */
        bitmask_index = pq_ctm_head >> INDEX_TO_BITMASK_SHIFT;
        index_in_bitmask = pq_ctm_head & INDEX_IN_BITMASK_MASK;

        /* If slot/head contains packet we dequeue it using LRU batch_out._pkt */
        if((bitmasks[bitmask_index] >> index_in_bitmask) & 1u) {
            switch (next_batch_out) {
                case 0: _DEQUEUE_PROC(0); break;
                case 1: _DEQUEUE_PROC(1); break;
                case 2: _DEQUEUE_PROC(2); break;
                case 3: _DEQUEUE_PROC(3); break;
                case 4: _DEQUEUE_PROC(4); break;
                case 5: _DEQUEUE_PROC(5); break;
                case 6: _DEQUEUE_PROC(6); break;
                case 7: _DEQUEUE_PROC(7); break;
            }

            next_batch_out++;

            /* Zero bitmask for this slot (ctm and lm) */
            bitmasks[bitmask_index] &= ~(1u << index_in_bitmask);

            lm_bitmasks[pq_lm_head >> INDEX_TO_BITMASK_SHIFT] &= 
                        ~(1u << (pq_lm_head & INDEX_IN_BITMASK_MASK) );
        }

        /* Let other threads know we have checked slot at head, 
            so we move pq_head one forward */
        pq_ctm_head++;
        if (pq_ctm_head == PQ_CTM_LENGTH) pq_ctm_head = 0;
        pq_lm_head++;
        if (pq_lm_head == PQ_LM_LENGTH) pq_lm_head = 0;
        pq_head_time += PQ_SLOT_TICKS; 

        pq_lm_dequeue_cnt++;
    }

    next_batch_out = 0;
}

__intrinsic uint32_t
pq_find_next_available_slot(uint32_t pq_d_index)
{
    uint32_t bitmask, i;
    uint32_t bitmask_index = pq_d_index >> INDEX_TO_BITMASK_SHIFT;
    uint32_t index_in_bitmask = pq_d_index & INDEX_IN_BITMASK_MASK;

    for (i = 0; i < 5; i++) {
        bitmask = ~bitmasks[bitmask_index];              /* 1 = available */

        /* Ignore bits below start index for first bitmask */
        bitmask &= (~0u << index_in_bitmask); 

        /* There is atleast one available space this bitmask */
        /* Go through bitmask until we find the slot */
        if (bitmask) {
            index_in_bitmask = 0;
            while ((bitmask & 1u) == 0) {
                bitmask >>= 1;
                index_in_bitmask++;
            }
            return (bitmask_index << INDEX_TO_BITMASK_SHIFT) + index_in_bitmask;
        }

        /* New bitmask to check */
        index_in_bitmask = 0;
        bitmask_index++;
        if (bitmask_index >= PQ_BITMASKS_LENGTH)
            bitmask_index = 0;
    }

    /* No slot found within 128-160 slots of initial */
    DEBUG(0x0002);
    halt();
    return 0;
}

/* --------------------------------------------------- */

/* XXX Move to some sort of CT reflect library */
__intrinsic void
reflect_data(unsigned int dst_me, unsigned int dst_ctx,
             unsigned int dst_xfer, unsigned int sig_no,
             __xwrite void *src_xfer, size_t size)
{
    unsigned int addr;
    unsigned int count = (size >> 2);
    struct nfp_mecsr_cmd_indirect_ref_0 indirect;

    /* ctassert(__is_write_reg(src_xfer)); */ /* TEMP, avoid volatile warnings */
    ctassert(__is_ct_const(size));

    /* Generic address computation.
     * Could be expensive if dst_me, or dst_xfer
     * not compile time constants */
    addr = ((dst_me & 0xFF0)<<20 | (dst_me & 0xF)<<10 |
            (dst_ctx & 7)<<7 | (dst_xfer & 0x3F)<<2);

    indirect.__raw = 0;
    if (sig_no != 0) {
        indirect.signal_num = sig_no;
        indirect.signal_ctx = dst_ctx;
    }
    local_csr_write(local_csr_cmd_indirect_ref_0, indirect.__raw);

    /* Currently just support reflect_write_sig_remote */
    /* XXX NFP_MECSR_PREV_ALU_OV_SIG_CTX_bit is next to SIG_NUM */
    __asm {
        alu[--, --, b, 3, <<NFP_MECSR_PREV_ALU_OV_SIG_NUM_bit];
        ct[reflect_write_sig_remote, *src_xfer, addr, 0, \
           __ct_const_val(count)], indirect_ref;
    };
}


__intrinsic void
copy_absolute_xfer(__shared __gpr unsigned int *dst, unsigned int src_xnum)
{
    /* XXX assumes src_xnum already accounts for CTX */
    local_csr_write(local_csr_t_index, MECSR_XFER_INDEX(src_xnum));
    __asm alu[*dst, --, B, *$index];
}


__intrinsic void
lso_ring_get(unsigned int rnum, mem_ring_addr_t raddr, unsigned int xnum,
             size_t size, sync_t sync, SIGNAL_PAIR *sigpair)
{
    unsigned int ind;
    unsigned int count = (size >> 2);

    ctassert(size != 0);
    ctassert(size <= (8 * 4));
    ctassert(__is_aligned(size, 4));
    ctassert(__is_ct_const(sync));
    ctassert(sync == sig_done);

    ind = NFP_MECSR_PREV_ALU_OVE_DATA(1);
    __asm {
        alu[--, ind, OR, xnum, <<(NFP_MECSR_PREV_ALU_DATA16_shift + 2)];
        mem[get, --, raddr, <<8, rnum, __ct_const_val(count)], indirect_ref, \
            sig_done[*sigpair];
    }
}


__intrinsic void
lso_msg_copy(__gpr struct nfd_in_lso_desc *lso_pkt, unsigned int xnum)
{
    local_csr_write(local_csr_t_index, MECSR_XFER_INDEX(xnum));
    __asm {
        alu[*lso_pkt.desc.__raw[0], --, B, *$index++];
        alu[*lso_pkt.desc.__raw[1], --, B, *$index++];
        alu[*lso_pkt.desc.__raw[2], --, B, *$index++];
        alu[*lso_pkt.desc.__raw[3], --, B, *$index++];
        alu[*lso_pkt.jumbo_seq, --, B, *$index++];
    }
}


/**
 * Assign addresses for "visible" transfer registers
 */
void
notify_setup_visible(void)
{
    __assign_relative_register(&notify_reset_state_xfer,
                               NFD_IN_NOTIFY_RESET_RD);
    __assign_relative_register(&nfd_in_data_compl_refl_in,
                               NFD_IN_NOTIFY_DATA_RD);
    __assign_relative_register(&nfd_in_jumbo_compl_refl_in,
                               NFD_IN_NOTIFY_JUMBO_RD);

    __implicit_write(&notify_reset_state_xfer);
    __implicit_write(&nfd_in_data_compl_refl_in);
    __implicit_write(&nfd_in_jumbo_compl_refl_in);
}


/**
 * Perform shared configuration for notify
 */
void
notify_setup_shared()
{
#ifdef NFD_IN_WQ_SHARED
    wq_num_base = NFD_RING_LINK(0, nfd_in, 0);
    wq_raddr = (unsigned long long) NFD_EMEM_SHARED(NFD_IN_WQ_SHARED) >> 8;
#else
    wq_num_base = NFD_RING_LINK(PCIE_ISL, nfd_in, 0);
    wq_raddr = (unsigned long long) NFD_EMEM_LINK(PCIE_ISL) >> 8;
#endif

    /* Kick off ordering */
    reorder_start(NFD_IN_NOTIFY_MANAGER0, &msg_order_sig);
    reorder_start(NFD_IN_NOTIFY_MANAGER0, &get_order_sig);
    reorder_start(NFD_IN_NOTIFY_MANAGER1, &msg_order_sig);
    reorder_start(NFD_IN_NOTIFY_MANAGER1, &get_order_sig);
}


/**
 * Perform per context initialization (for CTX 0 to 7)
 */
void
notify_setup(int side)
{
    dst_q = wq_num_base;
    wait_msk = __signals(&msg_sig0, &msg_sig1);

    next_ctx = reorder_get_next_ctx_off(ctx(), NFD_IN_NOTIFY_STRIDE);

#ifdef NFD_IN_LSO_CNTR_ENABLE
    /* get the location of LSO statistics */
    nfd_in_lso_cntr_addr =
        cntr64_get_addr((__mem40 void *) nfd_in_lso_cntrs);
#endif

    if (side == 0) {
        lso_ring_num = NFD_RING_LINK(PCIE_ISL, nfd_in_issued_lso,
                                     NFD_IN_ISSUED_LSO_RING0_NUM);
        lso_ring_addr = ((((unsigned long long)
                           NFD_EMEM_LINK(PCIE_ISL)) >> 32) << 24);
    } else {
        lso_ring_num =  NFD_RING_LINK(PCIE_ISL, nfd_in_issued_lso,
                                      NFD_IN_ISSUED_LSO_RING1_NUM);
        lso_ring_addr = ((((unsigned long long)
                           NFD_EMEM_LINK(PCIE_ISL)) >> 32) << 24);
    }

    /* ------ k_pace: init & setup ------- */

        /* Raised wq signals to signal that batch_out is available */
    raise_signal(&wq_sig0);
    raise_signal(&wq_sig1);
    raise_signal(&wq_sig2);
    raise_signal(&wq_sig3);
    raise_signal(&wq_sig4);
    raise_signal(&wq_sig5);
    raise_signal(&wq_sig6);
    raise_signal(&wq_sig7);

    /* Initialize head timer, and align it to slots */
    pq_head_time = get_current_time() & ~((uint64_t)PQ_SLOT_TICKS - 1ull);
}

#ifndef NFD_MU_PTR_DBG_MSK
#define NFD_MU_PTR_DBG_MSK 0x0f000000
#endif

#ifdef NFD_IN_NOTIFY_DBG_CHKS
#define _NOTIFY_MU_CHK(_pkt)                                            \
do {                                                                    \
    if ((batch_in.pkt##_pkt##.__raw[1] & NFD_MU_PTR_DBG_MSK) == 0) {    \
        /* Write the error we read to Mailboxes for debug purposes */   \
        local_csr_write(local_csr_mailbox_0,                            \
                        NFD_IN_NOTIFY_MU_PTR_INVALID);                  \
        local_csr_write(local_csr_mailbox_1,                            \
                        batch_in.pkt##_pkt##.__raw[1]);                 \
                                                                        \
        halt();                                                         \
    }                                                                   \
} while (0)
#else
#define _NOTIFY_MU_CHK(_pkt)                    \
do {} while (0)
#endif


#define _SEND_PACKET_TO_CTM(_out)                                       \
do {                                                                    \
    wait_for_all(&wq_sig##_out);                                        \
                                                                        \
    /* Prepare batch out */                                             \
    batch_out.pkt##_out##.__raw[0] = pkt_desc_tmp.__raw[0];             \
    batch_out.pkt##_out##.__raw[1] = (lm_batch_in.__raw[1]        \
                                            | notify_reset_state_gpr);  \
    batch_out.pkt##_out##.__raw[2] = lm_batch_in.__raw[2];        \
    /* k_pace: Zero vlan / l3_offset */                                 \
    batch_out.pkt##_out##.__raw[3] = lm_batch_in.__raw[3]         \
                                            &  0xFFFF0000;              \
                                                                        \
    /* Write packet to CTM */                                           \
    /* TODO: use least recently used batch out */                       \
    ctm_ptr = &ctm_pacing_queue[pq_index];                              \
    addr_hi = ((unsigned long long)ctm_ptr >> 8) & 0xff000000;          \
    addr_lo = ((unsigned long long)ctm_ptr & 0xffffffff);               \
    __asm {                                                             \
        mem[write, batch_out.pkt##_out##, addr_hi, <<8, addr_lo,        \
                        __ct_const_val(2)], sig_done[*wq_sig##_out]     \
    }                                                                   \
} while (0)

#define _SEND_PACKET_LSO_TO_CTM(_out)                                   \
do {                                                                    \
    wait_for_all(&wq_sig##_out);                                        \
                                                                        \
    /* Prepare batch out */                                             \
    batch_out.pkt##_out##.__raw[0] = pkt_desc_tmp.__raw[0];             \
    batch_out.pkt##_out##.__raw[1] = (lso_pkt.desc.__raw[1]             \
                                        |  notify_reset_state_gpr);     \
    batch_out.pkt##_out##.__raw[2] = lso_pkt.desc.__raw[2];             \
    /* k_pace: Zero vlan / l3_offset */                                 \
    batch_out.pkt##_out##.__raw[3] = lso_pkt.desc.__raw[3]              \
                                                & 0xFFFF0000;           \
                                                                        \
    /* Write packet to CTM */                                           \
    /* TODO: use least recently used batch out */                       \
    ctm_ptr = &ctm_pacing_queue[pq_index];                              \
    addr_hi = ((unsigned long long)ctm_ptr >> 8) & 0xff000000;          \
    addr_lo = ((unsigned long long)ctm_ptr & 0xffffffff);               \
    __asm {                                                             \
        mem[write, batch_out.pkt##_out##, addr_hi, <<8, addr_lo,        \
                        __ct_const_val(2)], sig_done[*wq_sig##_out]     \
    }                                                                   \
} while (0)


#define _NOTIFY_PROC                                                         \
do {                                                                         \
    /* --------------k_pace -------------------------- */                    \
    /* Read pacing rate + flow id from vlan field */                         \
    /* Use 12 for ns->ticks, results in firmware inserting 4% smaller gaps*/ \
    vlan_field = lm_batch_in.vlan;                                           \
    ipg_ticks = (vlan_field & 0x0FFF)*12; /* 250ns -> 20ns ticks */          \
    flow_id = (vlan_field >> 12) & 0x000F;                                   \
                                                                             \
    /* Calculate departure time for packet */                                \
    curtime = get_current_time();                                            \
    dep_time = flows_prev_dep_time[flow_id] + ipg_ticks;                     \
    if ( dep_time <= curtime) dep_time = curtime;                            \
    /* ----------------------------------------------- */                    \
                                                                             \
    /* finished packet and no LSO */                                         \
    if (lm_batch_in.eop) {                                                   \
                                                                             \
        __critical_path();                                                   \
        pkt_desc_tmp.is_nfd = lm_batch_in.eop;                               \
        pkt_desc_tmp.offset = lm_batch_in.offset;                            \
                                                                             \
        /* ======= Enqueue packet ===================================== */   \
                                                                             \
        /* -------------- Get index ------------- */                         \
        delta_slots = 0;                                                     \
                                                                             \
        /* Calculate packet slot based on how long in future from head */    \
        if (dep_time > pq_head_time)                                         \
            delta_slots = (uint32_t)((dep_time - pq_head_time) >>            \
                                                    PQ_TICKS_TO_SLOT_SHIFT); \
                                                                             \
        /* Ensure packet is not enqueued to far in future */                 \
        if (delta_slots >= PQ_TRESH_FUTURE_SLOTS)                            \
            delta_slots = PQ_TRESH_FUTURE_SLOTS;                             \
                                                                             \
        /* Find desired (CTM) slot to enqueue in relation to head */         \
        pq_d_index = pq_ctm_head + delta_slots;                              \
        if (pq_d_index >= PQ_CTM_LENGTH) pq_d_index -= PQ_CTM_LENGTH;        \
                                                                             \
        /* -------------- Find next available index ------------------ */    \
        pq_index = pq_find_next_available_slot(pq_d_index);                  \
                                                                             \
        /* Update delta_slots to reflect found slot */                       \
        delta_slots += PQ_CTM_RING_DIFF(pq_index, pq_d_index);               \
                                                                             \
        /* --------- Place packet in queue -------------- */                 \
                                                                             \
        /* Reflect that packet is enqueued by updating bitmask */            \
        /*  and last departure time of flow */                               \
        bitmasks[pq_index >> INDEX_TO_BITMASK_SHIFT] |=                      \
                                (1u << (pq_index & INDEX_IN_BITMASK_MASK));  \
        flows_prev_dep_time[flow_id] = dep_time;                             \
                                                                             \
        /* Place packet directly in lmem if close departure time */          \
        if (delta_slots < (PQ_LM_LENGTH-pq_lm_dequeue_cnt)) {                \
            /* convert index to lmem */                                      \
            pq_index = (pq_lm_head + delta_slots);                           \
            if (pq_index >= PQ_LM_LENGTH) pq_index -= PQ_LM_LENGTH;          \
                                                                                \
            /* Place packet in next available slot in pacing queue */           \
            lm_pacing_queue[pq_index].__raw[0] = pkt_desc_tmp.__raw[0];         \
            lm_pacing_queue[pq_index].__raw[1] = (lm_batch_in.__raw[1]          \
                                                    | notify_reset_state_gpr);  \
            lm_pacing_queue[pq_index].__raw[2] = lm_batch_in.__raw[2];          \
            /* k_pace: Zero vlan / l3_offset */                                 \
            lm_pacing_queue[pq_index].__raw[3] = lm_batch_in.__raw[3]           \
                                                    &  0xFFFF0000;              \
                                                                                \
            /* mark lmem slot as occupied, to prevent sync from overwriting */  \
            lm_bitmasks[pq_index >> INDEX_TO_BITMASK_SHIFT] |=                  \
                                (1u <<  (pq_index & INDEX_IN_BITMASK_MASK));    \
        } else {                                                                \
            /* -------- Send packet to CTM -------- */                       \
            __ctm40 void *ctm_ptr;                                           \
            unsigned int addr_hi, addr_lo;                                   \
                                                                             \
            switch (next_batch_out) {                                        \
                case 0: _SEND_PACKET_TO_CTM(0); break;                       \
                case 1: _SEND_PACKET_TO_CTM(1); break;                       \
                case 2: _SEND_PACKET_TO_CTM(2); break;                       \
                case 3: _SEND_PACKET_TO_CTM(3); break;                       \
                case 4: _SEND_PACKET_TO_CTM(4); break;                       \
                case 5: _SEND_PACKET_TO_CTM(5); break;                       \
                case 6: _SEND_PACKET_TO_CTM(6); break;                       \
                case 7: _SEND_PACKET_TO_CTM(7); break;                       \
            }                                                                \
                                                                             \
            next_batch_out++;                                                \
            next_batch_out &= 7;                                             \
        }                                                                    \
                                                                             \
                                                                             \
    } else if (lm_batch_in.lso != NFD_IN_ISSUED_DESC_LSO_NULL) {             \
        /* else LSO packets */                                               \
        __gpr struct nfd_in_lso_desc lso_pkt;                                \
        SIGNAL_PAIR lso_sig_pair;                                            \
        SIGNAL_MASK lso_wait_msk;                                            \
        __shared __gpr unsigned int jumbo_compl_seq;                         \
        int seqn_chk;                                                        \
                                                                             \
        /* XXX __signals(&lso_sig_pair.even) lists both even and odd */      \
        lso_wait_msk = 1 << __signal_number(&lso_sig_pair.even);             \
                                                                             \
                                                                             \
         /* finished packet with LSO to handle */                            \
        for (;;) {                                                           \
            /* read packet from nfd_in_issued_lso_ring */                    \
            lso_ring_get(lso_ring_num, lso_ring_addr, lso_xnum,              \
                         sizeof(lso_pkt), sig_done, &lso_sig_pair);          \
            wait_sig_mask(lso_wait_msk);                                     \
            __implicit_read(&lso_sig_pair.even);                             \
            while (signal_test(&lso_sig_pair.odd)) {                         \
                /* Ring get failed, retry */                                 \
                lso_ring_get(lso_ring_num, lso_ring_addr, lso_xnum,          \
                             sizeof(lso_pkt), sig_done, &lso_sig_pair);      \
                wait_for_all_single(&lso_sig_pair.even);                     \
            }                                                                \
            lso_msg_copy(&lso_pkt, lso_xnum);                                \
                                                                             \
                                                                             \
            /* Wait for the jumbo compl seq to catch up to the encoded seq */ \
            copy_absolute_xfer(&jumbo_compl_seq, jumbo_compl_xnum);          \
            seqn_chk = lso_pkt.jumbo_seq - jumbo_compl_seq;                  \
            while (seqn_chk > 0) {                                           \
                ctx_swap();                                                  \
                                                                             \
                copy_absolute_xfer(&jumbo_compl_seq, jumbo_compl_xnum);      \
                seqn_chk = lso_pkt.jumbo_seq - jumbo_compl_seq;              \
                                                                             \
                /* XXX we can also check for LSO DMA completions */          \
                /* by watching the data_dma_seq_compl, because they */       \
                /* both use the low priority DMA queue. */                   \
                copy_absolute_xfer(complete, data_compl_xnum);               \
                num_avail = *complete - *served;                             \
                if (num_avail > NFD_IN_MAX_BATCH_SZ) {                       \
                    /* There is at least one unserviced batch */             \
                    /* This guarantees that a DMA completed in our */        \
                    /* queue after the DMA we're waiting on. */              \
                    /* It's a worst case, because the 8x code in notify */   \
                    /* advances *served before this point */                 \
                    break;                                                   \
                }                                                            \
            }                                                                \
                                                                             \
            /* We can carry on processing the descriptor */                  \
            /* Check whether it should go to the app */                      \
            if (lso_pkt.desc.eop) {                                          \
                                                                             \
                pkt_desc_tmp.is_nfd = lso_pkt.desc.eop;                      \
                pkt_desc_tmp.offset = lso_pkt.desc.offset;                   \
                                                                             \
                /* ======= Enqueue packet ============================= */   \
                                                                             \
                /* -------------- Get index ------------- */                 \
                delta_slots = 0;                                             \
                                                                             \
                /* Calculate packet slot based on how long in future from head */ \
                if (dep_time > pq_head_time)                                 \
                    delta_slots = (uint32_t)((dep_time - pq_head_time) >>    \
                                                    PQ_TICKS_TO_SLOT_SHIFT); \
                                                                             \
                /* Ensure packet is not enqueued to far in future */         \
                if (delta_slots >= PQ_TRESH_FUTURE_SLOTS)                    \
                    delta_slots = PQ_TRESH_FUTURE_SLOTS;                     \
                                                                             \
                /* Find desired (CTM) slot to enqueue in relation to head */ \
                pq_d_index = pq_ctm_head + delta_slots;                      \
                if (pq_d_index >= PQ_CTM_LENGTH) pq_d_index -= PQ_CTM_LENGTH;\
                                                                             \
                /* -------------- Find next available index ------- */       \
                pq_index = pq_find_next_available_slot(pq_d_index);          \
                                                                             \
                /* Update delta_slots to reflect found slot */               \
                delta_slots += PQ_CTM_RING_DIFF(pq_index, pq_d_index);       \
                                                                             \
                /* --------- Place packet in queue -------------- */         \
                                                                             \
                /* Reflect that packet is enqueued by updating bitmask */    \
                bitmasks[pq_index >> INDEX_TO_BITMASK_SHIFT] |=              \
                                (1u << (pq_index & INDEX_IN_BITMASK_MASK));  \
                                                                             \
                /* Place packet directly in lmem if close departure time */  \
                if (delta_slots < (PQ_LM_LENGTH-pq_lm_dequeue_cnt)) {        \
                    /* convert index to lmem */                              \
                    pq_index = (pq_lm_head + delta_slots);                   \
                    if (pq_index >= PQ_LM_LENGTH) pq_index -= PQ_LM_LENGTH;  \
                                                                             \
                    /* Place packet in next available slot in pacing queue */   \
                    lm_pacing_queue[pq_index].__raw[0] = pkt_desc_tmp.__raw[0]; \
                    lm_pacing_queue[pq_index].__raw[1] = (lso_pkt.desc.__raw[1] \
                                                |  notify_reset_state_gpr);     \
                    lm_pacing_queue[pq_index].__raw[2] = lso_pkt.desc.__raw[2]; \
                    /* k_pace: Zero vlan / l3_offset */                         \
                    lm_pacing_queue[pq_index].__raw[3] = lso_pkt.desc.__raw[3]  \
                                                       & 0xFFFF0000;            \
                                                                                \
                    /* mark lmem slot as occupied, (prev sync from ovrwrt) */   \
                    lm_bitmasks[pq_index >> INDEX_TO_BITMASK_SHIFT] |=          \
                                (1u <<  (pq_index & INDEX_IN_BITMASK_MASK));    \
                } else {                                                        \
                    /* -------- Send packet to CTM -------- */                  \
                    __ctm40 void *ctm_ptr;                                      \
                    unsigned int addr_hi, addr_lo;                              \
                                                                                \
                    switch (next_batch_out) {                                \
                        case 0: _SEND_PACKET_LSO_TO_CTM(0); break;           \
                        case 1: _SEND_PACKET_LSO_TO_CTM(1); break;           \
                        case 2: _SEND_PACKET_LSO_TO_CTM(2); break;           \
                        case 3: _SEND_PACKET_LSO_TO_CTM(3); break;           \
                        case 4: _SEND_PACKET_LSO_TO_CTM(4); break;           \
                        case 5: _SEND_PACKET_LSO_TO_CTM(5); break;           \
                        case 6: _SEND_PACKET_LSO_TO_CTM(6); break;           \
                        case 7: _SEND_PACKET_LSO_TO_CTM(7); break;           \
                    }                                                        \
                                                                             \
                    next_batch_out++;                                        \
                    next_batch_out &= 7;                                     \
                }                                                            \
                                                                             \
                /* update departure time of next packet in tso chunk */      \
                dep_time += ipg_ticks;                                       \
                                                                             \
            }                                                                \
                                                                             \
            /* if it is last LSO being read from ring */                     \
            if (lso_pkt.desc.lso == NFD_IN_ISSUED_DESC_LSO_RET) {            \
                                                                             \
                /* k_pace: update last departure time (substract last add)*/ \
                flows_prev_dep_time[flow_id] = dep_time-ipg_ticks;           \
                                                                             \
                /* Break out of loop processing LSO ring */                  \
                break;                                                       \
            }                                                                \
        }                                                                    \
    }                                                                        \
} while (0)

__intrinsic void
sync_dequeue_loop() {
    wait_for_all(&get_order_sig);
    reorder_done_opt(&next_ctx, &get_order_sig);

    sync_ctm_lm();
    dequeue_pacing_queue();

    /* Participate in msg ordering */
    wait_for_all(&msg_order_sig);
    reorder_done_opt(&next_ctx, &msg_order_sig);
}

/**
 * Dequeue a batch of "issue_dma" messages and process that batch, incrementing
 * TX.R for the queue and adding an output message to one of the PCI.IN work
 * queueus.  An output message is only sent for the final message for a packet
 * (EOP bit set).  A count of the total number of descriptors in the batch is
 * added by the "issue_dma" block.
 *
 * We reorder before getting a batch of "issue_dma" messages and then ensure
 * batches are processed in order.  If there is no batch of messages to fetch,
 * we must still participate in the "msg_order_sig" ordering.
 */
__intrinsic void
_notify(__shared __gpr unsigned int *complete,
        __shared __gpr unsigned int *served,
        int input_ring, unsigned int data_compl_xnum,
        unsigned int jumbo_compl_xnum, unsigned int lso_xnum)
{

    unsigned int n_batch;
    unsigned int qc_queue;
    unsigned int num_avail;

    __xread struct _issued_pkt_batch batch_in;
    struct nfd_in_pkt_desc pkt_desc_tmp;

    __lmem struct nfd_in_issued_desc lm_batch_in;

    /* K_pace: variables we use to enqueue */
    uint16_t vlan_field;
    uint32_t flow_id, ipg_ticks, pq_index, pq_d_index, delta_slots;
    uint64_t dep_time, curtime;

    unsigned int i;

    /* Reorder before potentially issuing a ring get */
    wait_for_all(&get_order_sig);
    reorder_done_opt(&next_ctx, &get_order_sig);

    /* There is a FULL batch to process
     * XXX assume that issue_dma inc's dma seq for each nfd_in_issued_desc in
     * batch. */
    num_avail = *complete - *served;
    if (num_avail >= NFD_IN_MAX_BATCH_SZ)
    {
        /* Process whole batch */
        __critical_path();

        ctm_ring_get(NOTIFY_RING_ISL, input_ring, &batch_in.pkt0,
                     (sizeof(struct nfd_in_issued_desc) * 4), &msg_sig0);
        ctm_ring_get(NOTIFY_RING_ISL, input_ring, &batch_in.pkt4,
                     (sizeof(struct nfd_in_issued_desc) * 4), &msg_sig1);

        __asm {
            ctx_arb[--], defer[2];
            local_csr_wr[local_csr_active_ctx_wakeup_events, wait_msk];
            alu[*served, *served, +, NFD_IN_MAX_BATCH_SZ];
        }

        wait_msk = __signals(&qc_sig, &msg_sig0, &msg_sig1);
        __implicit_read(&qc_sig);
        __implicit_read(&msg_sig0);
        __implicit_read(&msg_sig1);

        /* Batches have a least one packet, but n_batch may still be
         * zero, meaning that the queue is down.  In this case, EOP for
         * all the packets should also be zero, so that notify will
         * essentially skip the batch.
         */
        n_batch = batch_in.pkt0.num_batch;

#ifdef NFD_VNIC_DBG_CHKS
        if (n_batch > NFD_IN_MAX_BATCH_SZ) {
            halt();
        }
#endif

        /* Interface and queue info are the same for all packets in batch */
        pkt_desc_tmp.intf = PCIE_ISL;
        pkt_desc_tmp.q_num = batch_in.pkt0.q_num;
#ifdef NFD_IN_ADD_SEQN
#else
        pkt_desc_tmp.seq_num = 0;
#endif

        for (i = 0; i < 8; i++) {
            /* Copy issued desc into LM */
            switch (i) {
                case 0: lm_batch_in = batch_in.pkt0; break;
                case 1: lm_batch_in = batch_in.pkt1; break;
                case 2: lm_batch_in = batch_in.pkt2; break;
                case 3: lm_batch_in = batch_in.pkt3; break;
                case 4: lm_batch_in = batch_in.pkt4; break;
                case 5: lm_batch_in = batch_in.pkt5; break;
                case 6: lm_batch_in = batch_in.pkt6; break;
                case 7: lm_batch_in = batch_in.pkt7; break;
            }
            _NOTIFY_PROC;
        }

        /* Map batch.queue to a QC queue and increment the TX_R pointer
         * for that queue by n_batch */
        qc_queue = NFD_NATQ2QC(NFD_BMQ2NATQ(batch_in.pkt0.q_num),
                               NFD_IN_TX_QUEUE);
        __qc_add_to_ptr_ind(PCIE_ISL, qc_queue, QC_RPTR, n_batch,
                            NFD_IN_NOTIFY_QC_RD, sig_done, &qc_sig);

    } else if (num_avail > 0) {
        /* There is a partial batch - process messages one at a time. */
        unsigned int partial_served = 0;

        wait_msk &= ~__signals(&msg_sig1);

        /* ctm_ring_get() uses sig_done */
        ctm_ring_get(NOTIFY_RING_ISL, input_ring, &batch_in.pkt0,
                     sizeof(struct nfd_in_issued_desc), &msg_sig0);

        wait_sig_mask(wait_msk);
        __implicit_read(&qc_sig);
        __implicit_read(&msg_sig0);


        /* This is the first message in the batch. Do not wait for
         * signals that will not be set while processing a partial
         * batch and store batch info. */
        n_batch = batch_in.pkt0.num_batch;
        qc_queue = NFD_NATQ2QC(NFD_BMQ2NATQ(batch_in.pkt0.q_num),
                               NFD_IN_TX_QUEUE);
        wait_msk = __signals(&msg_sig0);

        /* Interface and queue info is the same for all packets in batch */
        pkt_desc_tmp.intf = PCIE_ISL;
        pkt_desc_tmp.q_num = batch_in.pkt0.q_num;
#ifdef NFD_IN_ADD_SEQN
#else
        pkt_desc_tmp.seq_num = 0;
#endif

        for (;;) {
            /* Count the message and service it */
            partial_served++;
            lm_batch_in = batch_in.pkt0;
            _NOTIFY_PROC;

            /* Wait for new messages in ctm ring.
             * Note: other contexts should not fetch new messages or update
             *       'served' until this one has fetched BATCH_SZ messages. */
            while (num_avail <= partial_served) {
                ctx_wait(voluntary);
                /* Copy in reflected data without checking signals */
                copy_absolute_xfer(&notify_reset_state_gpr,
                                   NFD_IN_NOTIFY_RESET_RD);
                copy_absolute_xfer(complete, data_compl_xnum);

                num_avail = *complete - *served;
            }

            /* ctm_ring_get() uses sig_done */
            ctm_ring_get(NOTIFY_RING_ISL, input_ring, &batch_in.pkt0,
                         sizeof(struct nfd_in_issued_desc), &msg_sig0);

            /* We always service NFD_IN_MAX_BATCH_SZ messages */
            if (partial_served == (NFD_IN_MAX_BATCH_SZ - 1)) {
                break;
            }

            wait_sig_mask(wait_msk);
            __implicit_read(&msg_sig0);
        }

        /* We have finished fetching the messages from the ring.
         * Update served and allow other contexts to get messages
         * from ctm ring */
        *served += NFD_IN_MAX_BATCH_SZ;

        /* Wait for the last get to complete */
        wait_sig_mask(wait_msk);
        __implicit_read(&msg_sig0);

        /* Set up wait_msk to process a full batch next */
        /* XXX Assume we will do a WQ put, _NOTIFY_PROC will clear
           wq_sig0 if necessary */
        wait_msk = __signals(&msg_sig0, &msg_sig1, &qc_sig);

        /* Process the final descriptor from the batch */
        lm_batch_in = batch_in.pkt0;
        _NOTIFY_PROC;

        /* Increment the TX_R pointer for this queue by n_batch */
        __qc_add_to_ptr_ind(PCIE_ISL, qc_queue, QC_RPTR, n_batch,
                            NFD_IN_NOTIFY_QC_RD, sig_done, &qc_sig);

    }

    /* Participate in msg ordering */
    wait_for_all(&msg_order_sig);
    reorder_done_opt(&next_ctx, &msg_order_sig);
}


__intrinsic void
notify(int side)
{
    if (side == 0) {
        _notify(&data_dma_seq_compl0, &data_dma_seq_served0,
                NFD_IN_ISSUED_RING0_NUM,
                NFD_IN_NOTIFY_MANAGER0 << 5 | NFD_IN_NOTIFY_DATA_RD,
                NFD_IN_NOTIFY_MANAGER0 << 5 | NFD_IN_NOTIFY_JUMBO_RD,
                LSO_PKT_XFER_START0);
    } else {
        _notify(&data_dma_seq_compl1, &data_dma_seq_served1,
                NFD_IN_ISSUED_RING1_NUM,
                NFD_IN_NOTIFY_MANAGER1 << 5 | NFD_IN_NOTIFY_DATA_RD,
                NFD_IN_NOTIFY_MANAGER1 << 5 | NFD_IN_NOTIFY_JUMBO_RD,
                LSO_PKT_XFER_START1);
    }
}


/**
 * Participate in reordering with the workers
 */
__intrinsic void
notify_manager_reorder()
{
    /* Participate in ordering */
    wait_for_all(&get_order_sig);
    reorder_done_opt(&next_ctx, &get_order_sig);
    wait_for_all(&msg_order_sig);
    reorder_done_opt(&next_ctx, &msg_order_sig);
}


/**
 * Check autopush for seq_compl and reflect seq_served to issue_dma ME
 *
 * "data_dma_seq_compl" tracks the completed gather DMAs.  It is needed by
 * notify to determine when to service the "nfd_in_issued_ring".  The
 * issue_dma ME needs the sequence number more urgently (for in flight
 * DMA tracking) so it constructs the sequence number and reflects the
 * value to this ME.  It must be copied to shared GPRs for worker threads.
 *
 * "data_dma_seq_served" is state owned by this ME.  The issue_dma ME
 * needs the value to determine how many batches can be added to the
 * "nfd_in_issued_ring", so the current value is reflected to that
 * ME.  "data_dma_seq_sent" is used to track which sequence number
 * has been reflected, so that it is not resent.
 */
__intrinsic void
distr_notify(int side)
{
    __implicit_read(&nfd_in_jumbo_compl_refl_in);

    /* Store reset state in absolute GPR */
    copy_absolute_xfer(&notify_reset_state_gpr, NFD_IN_NOTIFY_RESET_RD);
    __implicit_read(&notify_reset_state_xfer);

    /* XXX prevent NFCC from removing the above copy as the shared
     * notify_reset_state_gpr is not used in this context */
    __implicit_read(&notify_reset_state_gpr);

    if (side == 0) {
#ifdef NFD_IN_HAS_ISSUE0
        data_dma_seq_compl0 = nfd_in_data_compl_refl_in;

        if (data_dma_seq_served0 != data_dma_seq_sent) {
            data_dma_seq_sent = data_dma_seq_served0;

            /* XXX reuse batch_out xfers on managers to avoid
             * live range issues */
            batch_out.pkt0.__raw[0] = data_dma_seq_sent;
            reflect_data(NFD_IN_DATA_DMA_ME0, NFD_IN_ISSUE_MANAGER,
                         __xfer_reg_number(&nfd_in_data_served_refl_in,
                                           NFD_IN_DATA_DMA_ME0),
                         __signal_number(&nfd_in_data_served_refl_sig,
                                         NFD_IN_DATA_DMA_ME0),
                         &batch_out.pkt0.__raw[0],
                         sizeof data_dma_seq_sent);
        }
#endif
    } else {

#ifdef NFD_IN_HAS_ISSUE1
        data_dma_seq_compl1 = nfd_in_data_compl_refl_in;

        if (data_dma_seq_served1 != data_dma_seq_sent) {
            data_dma_seq_sent = data_dma_seq_served1;

            /* XXX reuse batch_out xfers on managers to avoid
             * live range issues */
            batch_out.pkt0.__raw[0] = data_dma_seq_sent;
            reflect_data(NFD_IN_DATA_DMA_ME1, NFD_IN_ISSUE_MANAGER,
                         __xfer_reg_number(&nfd_in_data_served_refl_in,
                                           NFD_IN_DATA_DMA_ME1),
                         __signal_number(&nfd_in_data_served_refl_sig,
                                         NFD_IN_DATA_DMA_ME1),
                         &batch_out.pkt0.__raw[0],
                         sizeof data_dma_seq_sent);
        }
#endif
    }
}


int
main(void)
{
    /* Perform per ME initialisation  */
    notify_setup_visible();

    if (ctx() == 0) {
        /*
         * This function will start ordering for CTX0,
         * the manager for loop 0
         */
        notify_setup_shared();

        /* NFD_INIT_DONE_SET(PCIE_ISL, 2);     /\* XXX Remove? *\/ */

    }

    /* Test which side the context is servicing */
    if ((ctx() & (NFD_IN_NOTIFY_STRIDE - 1)) == 0) {

#ifdef NFD_IN_HAS_ISSUE0
        notify_setup(0);

        if (ctx() == NFD_IN_NOTIFY_MANAGER0) {

            __xread struct nfd_in_lso_desc lso_pkt0;
            __xread struct nfd_in_lso_desc lso_pkt1;

            __assign_relative_register(&lso_pkt0, LSO_PKT_XFER_START0);
            __assign_relative_register(&lso_pkt1, LSO_PKT_XFER_START1);

            for (;;) {
                notify_manager_reorder();
                notify_manager_reorder();
                distr_notify(0);
            }
        } else if (ctx() == 2) {
            for (;;) {
                notify(0);
            }
        } else {
            for (;;) {
                sync_dequeue_loop();
            }
        }
#else
        for (;;) {
            ctx_swap(kill);
        }
#endif

    } else {

#ifdef NFD_IN_HAS_ISSUE1
        notify_setup(1);

        if (ctx() == NFD_IN_NOTIFY_MANAGER1) {
            for (;;) {
                notify_manager_reorder();
                notify_manager_reorder();
                distr_notify(1);
            }
        } else if (ctx() == 3) {
            for (;;) {
                notify(1);
            }
        } else {
            for (;;) {
                sync_dequeue_loop();
            }
        }
#else
        for (;;) {
            ctx_swap(kill);
        }
#endif

    }
}
