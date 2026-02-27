/*
 * Copyright (C) 2015-2019,  Netronome Systems, Inc.  All rights reserved.
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
 * @file   msix_qmon.c
 * @brief  Monitor RX/TX queues and generate MSI-X on changes.
 */
#ifndef _BLOCKS__VNIC_SVC_MSIX_QMON_C_
#define _BLOCKS__VNIC_SVC_MSIX_QMON_C_

#include <nfp6000/nfp_me.h>

#include <assert.h>
#include <nfp.h>
#include <nfp_chipres.h>
#include <stdint.h>
#include <types.h>

#include <nfp/cls.h>
#include <nfp/me.h>
#include <nfp/mem_bulk.h>
#include <nfp/mem_atomic.h>
#include <std/reg_utils.h>

#include <vnic/nfd_common.h>
#include <vnic/pci_out.h>
#include <vnic/shared/nfd_cfg.h>
#include <vnic/shared/nfd_internal.h>
#include <vnic/svc/msix.h>
#include <vnic/utils/qcntl.h>

#include <nfp_net_ctrl.h>


/*
 * TODO:
 * - any other operation when link comes down?
 * - *maybe* read counters in bulk
 */


/*
 * This file implements the core of the logic for generating MSI-X for
 * packet transmit and receive.  At the core a single context per PCIe
 * Island is monitoring all of the active RX and TX queues for that
 * Island.  If changes to a queue are noticed, a MSI-X is generated.
 * This core logic also handles interrupt masking and the like and the
 * main entry point is implemented in @msix_qmon_loop().
 *
 * Since functions (PFs and VFs) as well as individual rings in these
 * functions can be configured dynamically at run-time, this file also
 * contains the logic for handling re-configurations.
 *
 * A general comment on terminology.  Through-out (unless for
 * identifiers from other files) we use the term "ring" when referring
 * to a queue or ring inside a VF/PF and the term "queue" when
 * referring to one of the 64 RX/TX queues available in total.  The
 * core MSI-X logic is only dealing with "queues" and configuration
 * logic translates from "rings" to queues.
 */

#define MAX_NUM_PCI_ISLS 4


/*
 * Create masks for PF and VF
 */
#define MSIX_RINGS_MASK(num_rings)  ((num_rings) == 64 ? 0xffffffffffffffff : \
                                     (1ull << (num_rings)) - 1)
#define MSIX_PF_RINGS_MASK          MSIX_RINGS_MASK(NFD_MAX_PF_QUEUES)
#ifdef NFD_USE_OVERSUBSCRIPTION
#define MSIX_LAST_PF_RINGS_MASK     MSIX_RINGS_MASK(NFD_LAST_PF_MAX_QUEUES)
#endif
#define MSIX_VF_RINGS_MASK          MSIX_RINGS_MASK(NFD_MAX_VF_QUEUES)
#define MSIX_CTRL_RINGS_MASK        MSIX_RINGS_MASK(NFD_MAX_CTRL_QUEUES)


/*
 * Interrupt Moderation support;
 *
 * 1) Constrain minimum time between interrupts for same queue
 *
 *    Wait for specified number of microseconds after RX/TX packet
 *    count changes before issuing an interrupt.
 *
 * 2) Issue interrupt if number of RX/TX packets since last interrupt
 *    exceeded some count
 *
 *    If number of RX/TX packets since last interrupt was issued
 *    for same queue exceeds the configured packet count, an interrupt
 *    is issued.
 */


/*
 * Configuration changes:
 *
 * When new rings get enabled (e.g. PFs or VFs are spun up or down)
 * context 0 in the service ME gets notified via suitable
 * configuration messages.  The MSI-X queue monitoring contexts then
 * needs to pick up the changes (like which queues are enabled, which
 * MSI-X entries to use etc).
 *
 * This process is split between context 0 and the MSI-X queue
 * monitoring contexts.  Context 0 is handling the conversion from
 * rings to queues and then writes the new state (plus additional
 * information to CLS, and signals the appropriate MSI-X queue
 * monitoring context.  The qmon context then simply copies the state
 * from CLS into its local state (some of which is held in local
 * registers for efficient access.  One the qmon context has updated
 * its locla state it signals back to context 0, which handles the
 * remainder of the configuration chain.
 *
 * Splitting the re-config handling relives pressure on GPRs and
 * allows the MSI-X queue monitoring contexts to maintain state in
 * registers which can't be shared (such as Next Neighbour
 * Registers). It also aids debugging as the state is externally
 * visible in CLS.
 *
 * @msix_qmon_reconfig() contains the code executed by context 0,
 * while @msix_local_reconfig() is the code executed by the MSI-X
 * queue monitoring context.
 *
 * Shared state (in CLS):
 * @msix_cls_rx_enabled      Bitmask of which RX queues are enabled
 * @msix_cls_tx_enabled      Bitmask of which TX queues are enabled
 * @msix_cls_rx_new_enabled  Bitmask of which new RX queues are being enabled
 * @msix_cls_tx_new_enabled  Bitmask of which new TX queues are being enabled
 * @msix_cls_automask        Bitmask of which queues should automask
 *
 * @msix_cls_rx_entries      Mapping of RX queue to MSI-X table entry
 * @msix_cls_tx_entries      Mapping of TX queue to MSI-X table entry
 *
 * @msix_rx_irqc_cfg         Interrupt coalescence settings for RX queues
 * @msix_tx_irqc_cfg         Interrupt coalescence settings for TX queues
 */
__shared __cls uint64_t msix_cls_rx_enabled[MAX_NUM_PCI_ISLS];
__shared __cls uint64_t msix_cls_tx_enabled[MAX_NUM_PCI_ISLS];
__shared __cls uint64_t msix_cls_rx_new_enabled[MAX_NUM_PCI_ISLS];
__shared __cls uint64_t msix_cls_tx_new_enabled[MAX_NUM_PCI_ISLS];
__shared __cls uint64_t msix_cls_automask[MAX_NUM_PCI_ISLS];

__shared __cls uint8_t msix_cls_rx_entries[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];
__shared __cls uint8_t msix_cls_tx_entries[MAX_NUM_PCI_ISLS][NFP_NET_TXR_MAX];

__shared __cls uint32_t msix_rx_irqc_cfg[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];
__shared __cls uint32_t msix_tx_irqc_cfg[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];

/*
 * Retrieve configured packet count and usec delay from interrupt
 * moderation config word
 */
#define MSIX_IRQC_CFG_PKTS(x) ((x) >> 16)
#define MSIX_IRQC_CFG_DLY(x)  ((x) & 0x0ffff)

/*
 * Default configuration for interrupt coaelesce/moderation
 * - sets packet count to 1
 * - sets usec delay to 0
 */
#define MSIX_IRQC_DEFAULT_CFG (1 << 16)

MSIX_DECLARE;

/*
 * Initialise the state (executed by context 0)
 *
 * Global variables are initialised to zero so init only the ones
 * which are not 0. This could/should be done via array init.
 */
void
msix_qmon_init(unsigned int pcie_isl)
{
    int i;
    __cls uint8_t *r = msix_cls_rx_entries[pcie_isl];
    __cls uint8_t *t = msix_cls_tx_entries[pcie_isl];
    __xwrite int tmp = 0xffffffff;

    for (i = 0; i < 64; i += 4) {
        cls_write(&tmp, r + i, sizeof(tmp));
        cls_write(&tmp, t + i, sizeof(tmp));
    }

    /* initialize RX interrupt moderation parameters */
    for (i = 0; i < NFP_NET_RXR_MAX; i++)
    msix_rx_irqc_cfg[pcie_isl][i] = MSIX_IRQC_DEFAULT_CFG;

    /* initialize TX interrupt moderation parameters */
    for (i = 0; i < NFP_NET_TXR_MAX; i++)
    msix_tx_irqc_cfg[pcie_isl][i] = MSIX_IRQC_DEFAULT_CFG;
}

/*
 * Reconfigure RX and TX rings (executed by context 0)
 *
 * @pcie_isl        PCIe Island this function is handling
 * @vid             vNIC inside the island this function is handling
 * @cfg_bar         Points to the control bar for the vnic
 * @rx_rings        Boolean, if set, handle RX rings, else RX rings
 * @vf_rings        Bitmask of enabled tings for the VF/vNIC.
 *
 * This function updates the internal state (used by other MEs) for
 * handling MSI-X generation for RX and TX rings. The logic is
 * identical for RX and TX rings, only different data structures are
 * updated.  This is a bit ugly, but the other option would be
 * significant code duplication, which isn't pretty either.
 *
 * Note: Some of the code generates contains CLS reads/writes.
 */
__intrinsic static void
msix_reconfig_rings(unsigned int pcie_isl, unsigned int vid,
                    __mem40 char *cfg_bar, int rx_rings, uint64_t vf_rings)
{
    unsigned int qnum;
    uint64_t rings;
    unsigned int ring;
    unsigned int entry;
    __xread unsigned int entry_r, tmp_r;
    __xwrite unsigned int tmp_w;
    __cls uint8_t *cls_addr;
    __mem40 char *entry_addr;

    uint64_t queues;
    uint64_t new_queues_en;
    uint64_t vf_queue_mask;

    /* Update the interrupt vector data, i.e. the MSI-X table entry
     * number, for all active rings. */
    rings = vf_rings;
    while (rings) {
        ring = ffs64(rings);
        rings &= rings - 1;

       /* Convert ring number to a queue number */
        qnum = NFD_VID2NATQ(vid, ring);

        /* Get MSI-X entry number and stash it into local memory */
        if (rx_rings) {
            entry_addr = cfg_bar + NFP_NET_CFG_RXR_VEC(ring);
            cls_addr = msix_cls_rx_entries[pcie_isl];
        } else {
            entry_addr = cfg_bar + NFP_NET_CFG_TXR_VEC(ring);
            cls_addr = msix_cls_tx_entries[pcie_isl];
        }
        mem_read32_le(&entry_r, entry_addr, sizeof(entry_r));
        entry = entry_r & 0xff;
        /* Write to CLS. We do this in BE format so it's easy to pick up */
        cls_addr += qnum;
        cls_read(&tmp_r, cls_addr, sizeof(tmp_r));
        tmp_w = (tmp_r & 0x00ffffff) | (entry << 24);
        cls_write(&tmp_w, cls_addr, sizeof(tmp_w));

        /* Make sure the ICR is reset */
        tmp_w = 0;
        mem_write8_le(&tmp_w, cfg_bar + NFP_NET_CFG_ICR(entry), 1);
    }

    /* Convert VF ring bitmask into Queue mask */
    queues = vf_rings << NFD_VID2NATQ(vid, 0);

    /* Work out which queues have been newly enabled and make sure
     * they don't have pending bits set. */
    if (rx_rings) {
        new_queues_en = (msix_cls_rx_enabled[pcie_isl] | queues) ^
            msix_cls_rx_enabled[pcie_isl];
        msix_cls_rx_new_enabled[pcie_isl] = new_queues_en;
    } else {
        new_queues_en = (msix_cls_tx_enabled[pcie_isl] | queues) ^
            msix_cls_tx_enabled[pcie_isl];
        msix_cls_tx_new_enabled[pcie_isl] = new_queues_en;
    }

    /* Update the enabled bit mask with queues for this VF. */
    if (NFD_VID_IS_PF(vid)) {
        vf_queue_mask = MSIX_PF_RINGS_MASK << NFD_VID2NATQ(vid, 0);
#ifdef NFD_USE_OVERSUBSCRIPTION
        if (vid == NFD_LAST_PF)
            vf_queue_mask = MSIX_LAST_PF_RINGS_MASK << NFD_VID2NATQ(vid, 0);
#endif
    } else if (NFD_VID_IS_CTRL(vid)) {
        vf_queue_mask = MSIX_CTRL_RINGS_MASK << NFD_VID2NATQ(vid, 0);
    } else {
        vf_queue_mask = MSIX_VF_RINGS_MASK << NFD_VID2NATQ(vid, 0);
    }

    if (rx_rings) {
        msix_cls_rx_enabled[pcie_isl] &= ~vf_queue_mask;
        msix_cls_rx_enabled[pcie_isl] |= queues;
    } else {
        msix_cls_tx_enabled[pcie_isl] &= ~vf_queue_mask;
        msix_cls_tx_enabled[pcie_isl] |= queues;
    }
}

/*
 * Reconfigure RX and TX rings (executed by context 0)
 *
 * @pcie_isl        PCIe Island this function is handling
 * @vid             vNIC inside the island this function is handling
 * @cfg_bar         Points to the control bar for the vnic
 * @rx_rings        Boolean, if set, handle RX rings, else RX rings
 * @vf_rings        Bitmask of enabled tings for the VF/vNIC.
 *
 * This function updates the internal state (used by other MEs) for
 * handling MSI-X generation for RX and TX rings. The logic is
 * identical for RX and TX rings, only different data structures are
 * updated.  This is a bit ugly, but the other option would be
 * significant code duplication, which isn't pretty either.
 *
 * Note: Some of the code generates contains CLS reads/writes.
 */
__intrinsic static void
msix_reconfig_irq_mod(unsigned int pcie_isl, unsigned int vid,
                      __mem40 char *cfg_bar, int rx_rings, uint64_t vf_rings)
{
    unsigned int qnum;
    uint64_t rings;
    unsigned int ring;
    __xread unsigned int entry_r;
    __mem40 char *entry_addr;

    /* Update the interrupt vector data, i.e. the MSI-X table entry
     * number, for all active rings. */
    rings = vf_rings;
    while (rings) {
        ring = ffs64(rings);
        rings &= rings - 1;

        /* Convert ring number to a queue number */
        qnum = NFD_VID2NATQ(vid, ring);

        /* Get interrupt moderation packet count and timeout and and stash
         * them into local memory */
        if (rx_rings)
            entry_addr = cfg_bar + NFP_NET_CFG_RXR_IRQ_MOD(ring);
        else
            entry_addr = cfg_bar + NFP_NET_CFG_TXR_IRQ_MOD(ring);

        mem_read32_le(&entry_r, entry_addr, sizeof(entry_r));

        if (rx_rings)
            msix_rx_irqc_cfg[pcie_isl][qnum] = entry_r;
        else
            msix_tx_irqc_cfg[pcie_isl][qnum] = entry_r;
    }
}

/*
 * Handle reconfiguration changes of RX queues (executed by context 0)
 *
 * @pcie_isl        PCIe Island this function is handling
 * @vid             vid of vNIC inside the island this function is handling
 * @cfg_bar         points to the control bar for the vnic
 * @cfg_bar_data[]  contains the first 6 words of the control bar.
 *
 * This function is called from context 0 of the service ME on
 * configuration.  The MSI-X queue monitoring code runs on different
 * contexts and this function updates the shared CLS data structures
 * before signalling the MSI-X contexts.
 *
 * Note: Some of the code contains implicit CLS reads/writes.
 */
__intrinsic void
msix_qmon_reconfig(unsigned int pcie_isl, unsigned int vid,
                   __mem40 char *cfg_bar, __xread unsigned int cfg_bar_data[6])
{
    unsigned int control, update;

    uint64_t vf_tx_rings_new;
    uint64_t vf_rx_rings_new;
    uint64_t queues;
    SIGNAL ack_sig;

    __assign_relative_register(&ack_sig, SVC_RECONFIG_SIG_NUM);

    control = cfg_bar_data[NFP_NET_CFG_CTRL >> 2];
    update = cfg_bar_data[NFP_NET_CFG_UPDATE >> 2];

    if (!(update & (NFP_NET_CFG_UPDATE_MSIX | NFP_NET_CFG_UPDATE_IRQMOD)))
        return;

    if (update & NFP_NET_CFG_UPDATE_MSIX) {

        /* Check if we are up */
        if (control & NFP_NET_CFG_CTRL_ENABLE) {
            vf_tx_rings_new =
                cfg_bar_data[(NFP_NET_CFG_TXRS_ENABLE >> 2) + 1];
            vf_tx_rings_new = ((vf_tx_rings_new << 32) |
                               cfg_bar_data[NFP_NET_CFG_TXRS_ENABLE >> 2]);
            vf_rx_rings_new =
                cfg_bar_data[(NFP_NET_CFG_RXRS_ENABLE >> 2) + 1];
            vf_rx_rings_new = ((vf_rx_rings_new << 32) |
                               cfg_bar_data[NFP_NET_CFG_RXRS_ENABLE >> 2]);
        } else if ((update & NFP_NET_CFG_UPDATE_GEN) &&
                   (!(control & NFP_NET_CFG_CTRL_ENABLE))) {
            /* The device got disabled */
            vf_tx_rings_new = 0;
            vf_rx_rings_new = 0;
        }

        /* Make sure the vnic is not configuring rings it has no control over */
        if (NFD_VID_IS_PF(vid)) {
#ifdef NFD_USE_OVERSUBSCRIPTION
            if (vid != NFD_LAST_PF) {
                vf_tx_rings_new &= MSIX_PF_RINGS_MASK;
                vf_rx_rings_new &= MSIX_PF_RINGS_MASK;
            } else {
                vf_tx_rings_new &= MSIX_LAST_PF_RINGS_MASK;
                vf_rx_rings_new &= MSIX_LAST_PF_RINGS_MASK;
            }
#else
            vf_tx_rings_new &= MSIX_PF_RINGS_MASK;
            vf_rx_rings_new &= MSIX_PF_RINGS_MASK;
#endif
        } else if (NFD_VID_IS_CTRL(vid)) {
            vf_tx_rings_new &= MSIX_CTRL_RINGS_MASK;
            vf_rx_rings_new &= MSIX_CTRL_RINGS_MASK;
        } else {
            vf_tx_rings_new &= MSIX_VF_RINGS_MASK;
            vf_rx_rings_new &= MSIX_VF_RINGS_MASK;
        }

        /* Avoiding TX interrupts if requested */
        if (control & NFP_NET_CFG_CTRL_MSIX_TX_OFF)
            vf_tx_rings_new = 0;


        /* Set MSI-X automask bits.  We assume that a VF/PF has the same
         * number of RX and TX rings and simple set the auto-mask bits for
         * all queues of the VF/PF depending on the auto-mask bit in the
         * control word. */
        queues = vf_rx_rings_new << NFD_VID2NATQ(vid, 0);

        if (control & NFP_NET_CFG_CTRL_MSIXAUTO)
            msix_cls_automask[pcie_isl] |= queues;
        else
            msix_cls_automask[pcie_isl] &= ~queues;

        /* Reconfigure the RX/TX ring state */
        msix_reconfig_rings(pcie_isl, vid, cfg_bar, 1, vf_rx_rings_new);
        msix_reconfig_rings(pcie_isl, vid, cfg_bar, 0, vf_tx_rings_new);
    }

    if (update & NFP_NET_CFG_UPDATE_IRQMOD) {

        vf_tx_rings_new =
            cfg_bar_data[(NFP_NET_CFG_TXRS_ENABLE >> 2) + 1];
        vf_tx_rings_new = ((vf_tx_rings_new << 32) |
                           cfg_bar_data[NFP_NET_CFG_TXRS_ENABLE >> 2]);
        vf_rx_rings_new =
            cfg_bar_data[(NFP_NET_CFG_RXRS_ENABLE >> 2) + 1];
        vf_rx_rings_new = ((vf_rx_rings_new << 32) |
                           cfg_bar_data[NFP_NET_CFG_RXRS_ENABLE >> 2]);

        msix_reconfig_irq_mod(pcie_isl, vid, cfg_bar, 1, vf_rx_rings_new);
        msix_reconfig_irq_mod(pcie_isl, vid, cfg_bar, 0, vf_tx_rings_new);

        /* if update did not include MSIX, ensure local reconfig does
         * use see any stale newly enabled RX/TX ring state */
        if (!(update & NFP_NET_CFG_UPDATE_MSIX)) {
            msix_cls_rx_new_enabled[pcie_isl] = 0;
            msix_cls_tx_new_enabled[pcie_isl] = 0;
        }
    }

    signal_ctx(pcie_isl + 1, SVC_RECONFIG_SIG_NUM);
    __implicit_write(&ack_sig);
    wait_for_all(&ack_sig);
}

/*
 * Code beyond this point is executed by the MSI-X queue monitoring contexts
 */

/*
 * Per PCIe Island state:
 * - @msix_rx_enabled: Bitmask of which RX queues are enabled
 * - @msix_tx_enabled: Bitmask of which TX queues are enabled
 * - @msix_rx_pending: Bitmask of which RX queues have pending interrupts
 * - @msix_tx_pending: Bitmask of which TX queues have pending interrupts
 * - @msix_automask:   Bitmask of which RX/TX queues should automask MSI-X
 *
 * - @msix_rx_entries: Indexed by RX Q, MSI-X table entry for this Q
 * - @msix_tx_entries: Indexed by TX Q, MSI-X table entry for this Q
 * - @prev_rx_cnt:     Indexed by RX Q, with the number of packets received
 * - @prev_tx_cnt:     Indexed by TX Q, with the number of packets transmitted
 *
 * We keep the first group state variables in Next Neighbour
 * Registers.  The second group is kept in local memory.  The local
 * memory variables are marked as shared and are arrays of arrays,
 * because otherwise something like uint32_t
 * msix_prev_rx_cnt[NFP_NET_RXR_MAX] would get allocated for *every*
 * context.
 *
 * XXX Global __nnr variables explicitly initialised to zero due to THSDK-2070
 */
__nnr static uint64_t msix_rx_enabled = 0;
__nnr static uint64_t msix_tx_enabled = 0;
__nnr static uint64_t msix_rx_pending = 0;
__nnr static uint64_t msix_tx_pending = 0;
__nnr static uint64_t msix_automask = 0;

__shared __lmem uint8_t msix_rx_entries[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];
__shared __lmem uint8_t msix_tx_entries[MAX_NUM_PCI_ISLS][NFP_NET_TXR_MAX];
__shared __lmem uint32_t msix_prev_rx_cnt[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];
__shared __lmem uint32_t msix_prev_tx_cnt[MAX_NUM_PCI_ISLS][NFP_NET_TXR_MAX];

/* maintains interrupt coalesce state or configuration for a given queue */
struct msix_irq_coalesce {
    uint32_t usecs;     /* time when 1st packet received */
    uint32_t frames;    /* number of packets received */
};

__shared __cls struct msix_irq_coalesce \
    msix_rx_irqc_state[MAX_NUM_PCI_ISLS][NFP_NET_RXR_MAX];

__shared __cls struct msix_irq_coalesce \
    msix_tx_irqc_state[MAX_NUM_PCI_ISLS][NFP_NET_TXR_MAX];


/*
 * Local reconfig
 *
 * Copy state from CLS into local state.  For newly enabled queues
 * reset some of the internal state and initialize the interrupt
 * moderation state.
 *
 * Note: Some of the code contains implicit CLS reads/writes.
 */
__intrinsic static void
msix_local_reconfig(const unsigned int pcie_isl)
{
    uint64_t new_enabled;
    __xread uint64_t tmp64;
    int qnum;
    __xread uint32_t entries[NFP_NET_RXR_MAX / 4];

    /*
     * Handle newly enabled queues (RX first, then TX)
     * - remove any pending bits.
     * - zero the count to keep track if new packets have been RXed/TXed
     *
     * Note: We use 'tmp64 &= tmp64 - 1' instead of 'tmp64 &= ~(1ull
     * << qnum)' to zero the first bit set because it removes
     * dependency on the _shl_64() intrinsic.
     */
    cls_read(&tmp64, &msix_cls_rx_new_enabled[pcie_isl], sizeof(tmp64));
    new_enabled = tmp64;
    msix_rx_pending &= ~new_enabled;
    while (new_enabled) {
        qnum = ffs64(new_enabled);
        new_enabled &= new_enabled - 1;
        msix_prev_rx_cnt[pcie_isl][qnum] = 0;
        msix_rx_irqc_state[pcie_isl][qnum].usecs = 0;
        msix_rx_irqc_state[pcie_isl][qnum].frames = 0;
    }

    cls_read(&tmp64, &msix_cls_tx_new_enabled[pcie_isl], sizeof(tmp64));
    new_enabled = tmp64;
    msix_tx_pending &= ~new_enabled;
    while (new_enabled) {
        qnum = ffs64(new_enabled);
        new_enabled &= new_enabled - 1;
        msix_prev_tx_cnt[pcie_isl][qnum] = 0;
        msix_tx_irqc_state[pcie_isl][qnum].usecs = 0;
        msix_tx_irqc_state[pcie_isl][qnum].frames = 0;
    }

    /* Update automask */
    cls_read(&tmp64, &msix_cls_automask[pcie_isl], sizeof(tmp64));
    msix_automask = tmp64;

    /* Copy entries */
    cls_read(&entries, msix_cls_rx_entries[pcie_isl], sizeof(entries));
    reg_cp(&msix_rx_entries[pcie_isl], entries, sizeof(entries));
    cls_read(&entries, msix_cls_tx_entries[pcie_isl], sizeof(entries));
    reg_cp(&msix_tx_entries[pcie_isl], entries, sizeof(entries));

    /* Copy enable bits */
    msix_rx_enabled = msix_cls_rx_enabled[pcie_isl];
    msix_tx_enabled = msix_cls_tx_enabled[pcie_isl];

    /* Clear pending on disabled queues */
    msix_rx_pending &= msix_rx_enabled;
    msix_tx_pending &= msix_tx_enabled;

    /* We are done. Signal context zero */
    signal_ctx(0, SVC_RECONFIG_SIG_NUM);
}


/*
 * Core MSI-X logic for generating interrupts for RX/TX queues
 */


/*
 * Read the number of packets received (and sent to host) from PCI.OUT.
 *
 * PCI.OUT maintains a table with two values per RX queue: a 32bit
 * credit counter and a 32bit packet counter.  These are atomically
 * incremented by PCI.OUT when packets are transmitted.  This function
 * reads the packet counter for a given queue.
 *
 * The index into the table is "a bit" strange. The table is organised
 * as follows:
 * q0(2x4B) q32(2x4B) q1(2x4B) q33(2x4B) ...
 * So, for RX queue 0, the values are at offset 0x0, for RX queue 1,
 * the values are at offset 0x10, for RX queue 32, the values are at
 * offset 0x8, etc.
 *
 * This ordering above is called the Bit Masked Queue Ordering in
 * PCI.OUT/PCI.IN and it get's it's name from the way the bitmasks
 * reported by the event filters are compacted.
 *
 * XXX This code *assumes* that the credits/packet counts are at
 * offset 0 in CTM of the relevant PCIe island.
 */
__intrinsic static uint32_t
msix_get_rx_queue_cnt(const unsigned int pcie_isl, unsigned int queue)
{
    unsigned int addr_hi;
    unsigned int addr_lo;
    __xread uint32_t rdata;
    SIGNAL rsig;

    /* Calculate the offset. */
    queue = NFD_NATQ2BMQ(queue);

    addr_hi = (0x84 | (pcie_isl + 4)) << 24;
    addr_lo = queue * NFD_OUT_ATOMICS_SZ + NFD_OUT_ATOMICS_SENT;

    __asm mem[atomic_read, rdata, addr_hi, <<8, addr_lo, 1], ctx_swap[rsig];

    return rdata;
}

/*
 * Used to moderate the rate of interrupts to specific RX/TX queue
 * by testing whether the interrupt can be issued or not base on
 * a) time since it last was issued for the same queue
 * b) if number of packets RXd/TXd since last IRQ exceeds some
 *    threshold
 * @pcie_isl:  PCIe Island number
 * @qnum:      Queue number
 * @rx_queue:  Boolean, set if this is for an RX queue, TX queue otherwise
 * @newpkts:   Nnumber of new TX/RX packets for given queue
 *
 * Returns 0 if interrupt may be issued or 1 if interrupt
 * can not be issued
 */
__intrinsic static int
msix_imod_check_can_send(const unsigned int pcie_isl, int qnum,
                         int rx_queue, unsigned int newpkts)
{
    uint32_t current_ts;
    uint32_t ts;
    uint32_t pcnt;
    uint32_t ticks;
    uint32_t cfg_irqc_ticks;
    uint32_t cfg_irqc_pkts;

    current_ts = (uint32_t)me_tsc_read();

    if (rx_queue) {
        ts   = msix_rx_irqc_state[pcie_isl][qnum].usecs;
        pcnt = msix_rx_irqc_state[pcie_isl][qnum].frames;
    }
    else {
        ts   = msix_tx_irqc_state[pcie_isl][qnum].usecs;
        pcnt = msix_tx_irqc_state[pcie_isl][qnum].frames;
    }

    pcnt += newpkts;

    if (rx_queue)
        msix_rx_irqc_state[pcie_isl][qnum].frames = pcnt;
    else
        msix_tx_irqc_state[pcie_isl][qnum].frames = pcnt;

    if (!ts) {
        if (rx_queue)
            msix_rx_irqc_state[pcie_isl][qnum].usecs = current_ts;
        else
            msix_tx_irqc_state[pcie_isl][qnum].usecs = current_ts;

        ts = current_ts;
    }

    if (rx_queue) {
        cfg_irqc_ticks = MSIX_IRQC_CFG_DLY(msix_rx_irqc_cfg[pcie_isl][qnum]);
        cfg_irqc_pkts = MSIX_IRQC_CFG_PKTS(msix_rx_irqc_cfg[pcie_isl][qnum]);
    } else {
        cfg_irqc_ticks = MSIX_IRQC_CFG_DLY(msix_tx_irqc_cfg[pcie_isl][qnum]);
        cfg_irqc_pkts = MSIX_IRQC_CFG_PKTS(msix_tx_irqc_cfg[pcie_isl][qnum]);
    }

    ticks = current_ts - ts;

    /*
     * limited documentation from
     * https://github.com/torvalds/linux/blob/v3.13/include/uapi/linux/ethtool.h#L232
     * this is implemented in the next 2 if blocks:
     *
     * (usecs > 0 && time_since_first_completion >= usecs) ||
     * (max_frames > 0 && completed_frames >= max_frames)
     */
    if (cfg_irqc_ticks && (ticks >= cfg_irqc_ticks))
        return 0;

    if (cfg_irqc_pkts && (pcnt >= cfg_irqc_pkts))
        return 0;

    /*
     * usecs = 0 is special, along with max_frames = 1 disables
     * coalescing, along with max_frames > 1 is undocumented, choosing
     * to disable coalescing. Both usec and max_frames is illegal so
     * no need to check for max_frames (cfg_irq_pkts)
     */
    if (!cfg_irqc_ticks)
        return 0;

    return 1;
}

/*
 * Performs cleanup of interrupt moderation support after an
 * interrupt has been successfully issued
 * @pcie_isl:  PCIe Island number
 * @qnum:      Queue number
 * @rx_queue:  Boolean, set if this is for an RX queue, TX queue otherwise
 */
__intrinsic static void
msix_imod_irq_issued(const unsigned int pcie_isl, int qnum, int rx_queue)
{
    if (rx_queue) {
        msix_rx_irqc_state[pcie_isl][qnum].usecs = 0;
        msix_rx_irqc_state[pcie_isl][qnum].frames = 0;
        /* clear TX timestamp too if vector is shared */
        if (msix_rx_entries[pcie_isl][qnum] ==
            msix_tx_entries[pcie_isl][qnum]) {
            msix_tx_irqc_state[pcie_isl][qnum].usecs = 0;
            msix_tx_irqc_state[pcie_isl][qnum].frames = 0;
        }
    } else {
        msix_tx_irqc_state[pcie_isl][qnum].usecs = 0;
        msix_tx_irqc_state[pcie_isl][qnum].frames = 0;
        /* clear RX timestamp too if vector is shared */
        if (msix_rx_entries[pcie_isl][qnum] ==
            msix_tx_entries[pcie_isl][qnum]) {
            msix_rx_irqc_state[pcie_isl][qnum].usecs = 0;
            msix_rx_irqc_state[pcie_isl][qnum].frames = 0;
        }
    }
}

/*
 * Updates the packet count for given PCIe island, queue number and queue type
 * and returns with the count of new packets
 * @pcie_isl:  PCIe Island number
 * @qnum:      Queue number
 * @rx_queue:  Boolean, set if this is for an RX queue, TX queue otherwise
 * @count:     Current number of TX/RX packets for given queue
 *
 * Returns number of new RX/TX packets
 */
__intrinsic static unsigned int
msix_update_packet_count(const unsigned int pcie_isl, int qnum,
                         int rx_queue, unsigned int count)
{
    uint32_t oldpkts;
    uint32_t newpkts;

    /* get previous count */
    if (rx_queue)
        oldpkts = msix_prev_rx_cnt[pcie_isl][qnum];
    else
        oldpkts = msix_prev_tx_cnt[pcie_isl][qnum];

    /* determine change in number of packets */
    newpkts = count - oldpkts;

    /* Update the count to the new value */
    if (rx_queue)
        msix_prev_rx_cnt[pcie_isl][qnum] = count;
    else
        msix_prev_tx_cnt[pcie_isl][qnum] = count;

    return newpkts;
}

/*
 * Attempt to send an MSI-X for a given queue
 * @pcie_isl:  PCIe Island number
 * @qnum:      Queue number
 * @rx_queue:  Boolean, set if this is for an RX queue, TX queue otherwise
 * @count:     Current number of TX/RX packets for given queue
 *
 * Returns 0 on success.  Otherwise the interrupt is masked in some way.
 *
 * If MSI-X auto-masking is enabled for the function, just go with
 * that.  If MSI-X auto-masking is disabled, check the ICR for the
 * entry in the function configuration BAR.  If not set, set it and
 * attempt to generate a MSI-X.  If the ICR is already set, then the
 * entry is already "masked".
 */
__intrinsic static int
msix_send_q_irq(const unsigned int pcie_isl, int qnum, int rx_queue,
                unsigned int count)
{
    unsigned int automask;
    unsigned int entry;
    int vid, vqn;
    uint64_t cfg_bar;
    __xread uint32_t mask_r;
    __xwrite uint32_t mask_w;

    int ret;

    /* apply interrupt moderation */
    if (msix_imod_check_can_send(pcie_isl, qnum, rx_queue, count)) {
        ret = 1;
        goto out;
    }

    /* get MSI-X table entry value for the queue */
    if (rx_queue)
        entry = msix_rx_entries[pcie_isl][qnum];
    else
        entry = msix_tx_entries[pcie_isl][qnum];

    /* Should we automask this queue? */
    automask = msix_automask & (1ull << qnum);

    /* Get the vNIC vid and queue number */
    NFD_NATQ2VID(vid, vqn, qnum);

    /* If we don't use auto-masking, check (and update) the ICR */
    if (!automask) {
        cfg_bar = NFD_CFG_BAR(msix_cfg_bars[pcie_isl], vid);
        cfg_bar += NFP_NET_CFG_ICR(entry);
        mem_read32_le(&mask_r, (__mem40 void *)cfg_bar, sizeof(mask_r));
        if (mask_r & 0x000000ff) {
            ret = 1;
            goto out;
        }
        mask_w = NFP_NET_CFG_ICR_RXTX;
        mem_write8_le(&mask_w, (__mem40 void *)cfg_bar, 1);
    }

    if (NFD_VID_IS_VF(vid))
        ret = msix_vf_send(pcie_isl, PCIE_CPP2PCIE_QMON, vid,
                           entry, automask);
    else
        ret = msix_pf_send(pcie_isl, PCIE_CPP2PCIE_QMON, entry, automask);

    /* IRQ issued, cleanup interrupt moderation state */
    if (!ret)
        msix_imod_irq_issued(pcie_isl, qnum, rx_queue);

out:
    return ret;
}

/*
 * The main monitoring loop.
 */
__forceinline void
msix_qmon_loop(const unsigned int pcie_isl)
{
    int qnum;
    uint32_t count;
    uint32_t newpkts;
    uint64_t qmask;
    uint64_t enabled, pending;
    int ret;

    SIGNAL reconfig_sig;

    __assign_relative_register(&reconfig_sig, SVC_RECONFIG_SIG_NUM);

    for (;;) {

        if (signal_test(&reconfig_sig))
            msix_local_reconfig(pcie_isl);

        /*
         * Check enabled RX and TX queues.
         * Read their respective counts and if they changed try to
         * send an interrupt (RX) or mark them as pending (TX).
         */
        enabled = msix_rx_enabled;
        while (enabled) {
            qnum = ffs64(enabled);
            qmask = 1ull << qnum;
            enabled &= ~qmask;

            /* Check if queue got new packets and try to send MSI-X if so */
            count = msix_get_rx_queue_cnt(pcie_isl, qnum);
            if (count != msix_prev_rx_cnt[pcie_isl][qnum]) {

                newpkts = msix_update_packet_count(pcie_isl, qnum, 1, count);

                /* try to issue irq for the queue */
                ret = msix_send_q_irq(pcie_isl, qnum, 1, newpkts);

                /* If un-successful, mark queue in the pending mask */
                if (ret) {
                    msix_rx_pending |= qmask;
                } else {
                    msix_rx_pending &= ~qmask;
                    if (msix_rx_entries[pcie_isl][qnum] ==
                        msix_tx_entries[pcie_isl][qnum])
                        msix_tx_pending &= ~qmask;
                }
            }
        }

        enabled = msix_tx_enabled;
        while (enabled) {
            qnum = ffs64(enabled);
            qmask = 1ull << qnum;
            enabled &= ~qmask;

            /* Check if queue got new packets and try to send MSI-X if so */
            count = qc_read(pcie_isl,
                            NFD_NATQ2QC(qnum, NFD_IN_TX_QUEUE), QC_RPTR);
            count = NFP_QC_STS_LO_READPTR_of(count);
            if (count != msix_prev_tx_cnt[pcie_isl][qnum]) {
                newpkts = msix_update_packet_count(pcie_isl, qnum, 0, count);
                msix_imod_check_can_send(pcie_isl, qnum, 0, newpkts);
                msix_tx_pending |= qmask;
            }
        }

        /*
         * Handle pending Interrupts. RX first, then TX.  If a RX
         * queue and a TX queue share the same MSI-X entry (very
         * likely) then remove them from the respective other pending
         * mask.  Also update the respective RX/TX count in case new
         * packets were received/trasnmitted since we last checked.
         */
        pending = msix_rx_pending;
        while (pending) {
            qnum = ffs64(pending);
            qmask = 1ull << qnum;
            pending &= ~qmask;

            /* Update RX queue count in case it changed. */
            count = msix_get_rx_queue_cnt(pcie_isl, qnum);
            newpkts = msix_update_packet_count(pcie_isl, qnum, 1, count);

            /* Try to send MSI-X. If successful remove from pending */
            ret = msix_send_q_irq(pcie_isl, qnum, 1, newpkts);
            if (!ret) {
                msix_rx_pending &= ~qmask;
                if (msix_rx_entries[pcie_isl][qnum] ==
                    msix_tx_entries[pcie_isl][qnum])
                    msix_tx_pending &= ~qmask;
            }
        }

        pending = msix_tx_pending;
        while (pending) {
            qnum = ffs64(pending);
            qmask = 1ull << qnum;
            pending &= ~qmask;

            /* Update TX queue count in case it changed. */
            count = qc_read(pcie_isl, NFD_NATQ2QC(qnum, NFD_IN_TX_QUEUE),
                            QC_RPTR);
            count = NFP_QC_STS_LO_READPTR_of(count);

            newpkts = msix_update_packet_count(pcie_isl, qnum, 0, count);

            /* Try to send MSI-X. If successful remove from pending */
            ret = msix_send_q_irq(pcie_isl, qnum, 0, newpkts);
            if (!ret) {
                msix_tx_pending &= ~qmask;
                if (msix_tx_entries[pcie_isl][qnum] ==
                    msix_rx_entries[pcie_isl][qnum])
                    msix_rx_pending &= ~qmask;
            }
        }

        /* In the loop above we perform sufficient IO for others to
         * run, but give them another chance here. */
        ctx_swap();
    }
}

#endif /* !_BLOCKS__VNIC_SVC_MSIX_QMON_C_ */
