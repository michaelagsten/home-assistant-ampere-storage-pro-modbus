#include "sd.h"
#include "sdhci.h"
#include "../drivers/uart.h"

#include <stdint.h>

/* ------------------------------------------------------------------ */
/* Hardware register accessors                                         */
/* ------------------------------------------------------------------ */

static inline volatile uint8_t *r8(uint32_t off)
{
    return (volatile uint8_t *)(SDHOST_BASE + off);
}
static inline volatile uint16_t *r16(uint32_t off)
{
    return (volatile uint16_t *)(SDHOST_BASE + off);
}
static inline volatile uint32_t *r32(uint32_t off)
{
    return (volatile uint32_t *)(SDHOST_BASE + off);
}

/* ------------------------------------------------------------------ */
/* Accurate microsecond delay using the AArch64 system counter         */
/*                                                                     */
/* CNTFRQ_EL0 contains the counter frequency in Hz (set by firmware). */
/* CNTPCT_EL0 is the free-running physical counter.                   */
/* Both are readable from EL1 without any additional setup.           */
/* ------------------------------------------------------------------ */
static void delay_us(uint32_t us)
{
    uint64_t freq, start, now;
    __asm__ volatile ("mrs %0, cntfrq_el0" : "=r"(freq));
    __asm__ volatile ("mrs %0, cntpct_el0" : "=r"(start));
    uint64_t ticks = (freq / 1000000ULL) * (uint64_t)us;
    do {
        __asm__ volatile ("mrs %0, cntpct_el0" : "=r"(now));
    } while ((now - start) < ticks);
}

/* ------------------------------------------------------------------ */
/* Module state                                                        */
/* ------------------------------------------------------------------ */

static int      is_sdhc;    /* 1 = SDHC/SDXC (sector-addressed), 0 = SDSC */
static uint32_t card_rca;   /* Relative Card Address (16-bit, used in CMD7)*/
static uint32_t base_clock; /* SDHCI base clock in Hz (read from Caps reg) */

/* ------------------------------------------------------------------ */
/* SDHCI helpers                                                       */
/* ------------------------------------------------------------------ */

static void sdhci_reset(uint8_t mask)
{
    *r8(SDHCI_SW_RESET) = mask;
    /* Poll until reset bit self-clears (controller done) */
    uint32_t timeout = 100000u;
    while ((*r8(SDHCI_SW_RESET) & mask) && --timeout)
        delay_us(1);
}

/*
 * Configure the SDCLK frequency.
 * target_hz — desired clock in Hz (e.g. 400000 for init, 25000000 normal)
 *
 * Uses SDHCI 2.0 8-bit divider mode:  SDCLK = base_clock / (2 × N)
 * N = 0 → SDCLK = base_clock (no division).
 */
static void sdhci_set_clock(uint32_t target_hz)
{
    /* Disable SD clock while reconfiguring */
    uint16_t ctrl = *r16(SDHCI_CLK_CTRL);
    *r16(SDHCI_CLK_CTRL) = (uint16_t)(ctrl & ~CLK_SDCLK_EN);
    delay_us(200);

    /* Calculate smallest N such that base_clock / (2×N) ≤ target_hz */
    uint32_t n = 1;
    if (target_hz > 0 && base_clock > 0) {
        n = (base_clock + 2u * target_hz - 1u) / (2u * target_hz);
        if (n == 0) n = 1;
        if (n > 0xFF) n = 0xFF;
    }

    /* Enable internal clock with computed divider */
    *r16(SDHCI_CLK_CTRL) = CLK_DIV(n) | CLK_INT_EN;

    /* Wait for internal clock to stabilise (max 150 ms per spec) */
    uint32_t timeout = 150000u;
    while (!(*r16(SDHCI_CLK_CTRL) & CLK_INT_STABLE) && --timeout)
        delay_us(1);

    /* Enable SD clock output */
    *r16(SDHCI_CLK_CTRL) = (uint16_t)(*r16(SDHCI_CLK_CTRL) | CLK_SDCLK_EN);
    delay_us(200);
}

/* ------------------------------------------------------------------ */
/* Command engine                                                      */
/* ------------------------------------------------------------------ */

/*
 * Send one SD command and collect the response.
 *
 * idx      — command index (0–63)
 * arg      — 32-bit argument
 * cmd_flags — CMD_RESP_* | CMD_CRC_EN | CMD_IDX_EN | CMD_DATA_PRESENT etc.
 * resp     — 4 × 32-bit response words (may be NULL if not needed)
 *
 * Returns SD_OK or SD_ERR_TIMEOUT.
 */
static sd_result_t send_cmd(uint8_t idx, uint32_t arg,
                            uint16_t cmd_flags, uint32_t *resp)
{
    /* Determine which inhibit bits to check */
    uint32_t inhibit = PSTATE_CMD_INHIBIT;
    if (cmd_flags & CMD_DATA_PRESENT)
        inhibit |= PSTATE_DAT_INHIBIT;
    /* R1b also requires DAT line to be free before next command */
    if ((cmd_flags & 0x3u) == CMD_RESP_48_BUSY)
        inhibit |= PSTATE_DAT_INHIBIT;

    /* Wait for the bus to be free */
    uint32_t timeout = 200000u;
    while ((*r32(SDHCI_PRESENT_STATE) & inhibit) && --timeout)
        delay_us(1);
    if (!timeout) {
        uart_puts("  [SD] CMD"); uart_putu32(idx);
        uart_putln(" inhibit timeout");
        return SD_ERR_TIMEOUT;
    }

    /* Clear any stale interrupt status */
    *r16(SDHCI_INT_STATUS) = INT_ALL;
    *r16(SDHCI_ERR_STATUS) = INT_ALL;

    /* Write argument and fire command */
    *r32(SDHCI_ARG1) = arg;
    *r16(SDHCI_COMMAND) = MAKE_CMD(idx, cmd_flags);

    /* Poll for Command Complete or Error (max 500 ms) */
    timeout = 500000u;
    uint16_t st;
    do {
        st = *r16(SDHCI_INT_STATUS);
    } while (!(st & (INT_CMD_COMPLETE | INT_ERROR)) && --timeout);

    if (!timeout || (st & INT_ERROR)) {
        uint16_t err = *r16(SDHCI_ERR_STATUS);
        uart_puts("  [SD] CMD"); uart_putu32(idx);
        uart_puts(" err: int="); uart_puthex64(st);
        uart_puts(" errreg="); uart_puthex64(err);
        uart_puts("\r\n");
        sdhci_reset(SW_RESET_CMD | SW_RESET_DAT);
        return SD_ERR_TIMEOUT;
    }

    *r16(SDHCI_INT_STATUS) = INT_CMD_COMPLETE;

    if (resp) {
        resp[0] = *r32(SDHCI_RESPONSE0);
        resp[1] = *r32(SDHCI_RESPONSE1);
        resp[2] = *r32(SDHCI_RESPONSE2);
        resp[3] = *r32(SDHCI_RESPONSE3);
    }

    return SD_OK;
}

/* Application-specific command: send CMD55 first, then the ACMD */
static sd_result_t send_acmd(uint8_t acmd_idx, uint32_t arg,
                             uint16_t cmd_flags, uint32_t *resp)
{
    uint32_t dummy[4];
    sd_result_t r = send_cmd(55, (uint32_t)card_rca << 16,
                              SD_CMD55_FLAGS, dummy);
    if (r != SD_OK) return r;
    return send_cmd(acmd_idx, arg, cmd_flags, resp);
}

/* ------------------------------------------------------------------ */
/* SD card initialisation sequence                                     */
/* ------------------------------------------------------------------ */

sd_result_t sd_init(void)
{
    uart_puts("  [SD] Initialising SDHCI @ ");
    uart_puthex64(SDHOST_BASE);
    uart_puts("\r\n");

    /* 1. Full controller reset */
    sdhci_reset(SW_RESET_ALL);

    /* 2. Read base clock from Capabilities register */
    uint32_t caps = *r32(SDHCI_CAPABILITIES0);
    uint32_t base_mhz = (caps & CAP0_BASE_CLK_MASK) >> CAP0_BASE_CLK_SHIFT;
    base_clock = base_mhz * 1000000u;
    if (base_clock == 0) {
        /* Fallback: assume 52 MHz (common for BCM2712) */
        base_clock = 52000000u;
    }
    uart_puts("  [SD] Base clock: "); uart_putu32(base_clock / 1000000u);
    uart_putln(" MHz");

    /* 3. Enable interrupts in status register (status-only; no IRQ signals) */
    *r16(SDHCI_INT_ENABLE) = 0xFFFFu;
    *r16(SDHCI_ERR_ENABLE) = 0xFFFFu;
    /* Keep signal enable at 0 (polling, no actual interrupts) */

    /* 4. Set identification clock: 400 kHz */
    sdhci_set_clock(400000u);

    /* 5. Power on at 3.3 V */
    *r8(SDHCI_POWER_CTRL) = PWR_330V | PWR_ON;
    delay_us(1000);

    /* 6. Check card presence */
    if (!(*r32(SDHCI_PRESENT_STATE) & PSTATE_CARD_INSERTED)) {
        uart_putln("  [SD] No card detected");
        return SD_ERR_NO_CARD;
    }
    uart_putln("  [SD] Card detected");

    /* 7. CMD0 — GO_IDLE_STATE: reset card to idle */
    send_cmd(0, 0, SD_CMD0_FLAGS, NULL);
    delay_us(2000);

    /* 8. CMD8 — SEND_IF_COND: check voltage range (required for SDHC) */
    /*    Argument: VHS=0x1 (2.7–3.6V), check pattern=0xAA             */
    uint32_t resp[4] = {0};
    sd_result_t r = send_cmd(8, 0x000001AAu, SD_CMD8_FLAGS, resp);
    int v2_card = (r == SD_OK && (resp[0] & 0xFFu) == 0xAAu);

    /* 9. ACMD41 — SD_SEND_OP_COND: repeatedly until card is ready (≤1 s) */
    /*    HCS=1 (we support SDHC), XPC=1 (max performance), request 3.3V  */
    uint32_t acmd41_arg = 0x40FF8000u;   /* HCS | voltage window           */
    if (!v2_card) acmd41_arg &= ~(1u << 30); /* Clear HCS for SDSC v1 cards */

    card_rca = 0;   /* Not yet set; CMD55 with RCA=0 during init */
    int ready = 0;
    for (int attempt = 0; attempt < 1000; attempt++) {
        r = send_acmd(41, acmd41_arg, SD_ACMD41_FLAGS, resp);
        if (r == SD_OK && (resp[0] & (1u << 31))) {
            ready = 1;
            break;
        }
        delay_us(1000);
    }
    if (!ready) {
        uart_putln("  [SD] ACMD41 timeout: card not ready");
        return SD_ERR_INIT;
    }

    is_sdhc = (resp[0] & (1u << 30)) ? 1 : 0;
    uart_puts("  [SD] Card type: ");
    uart_putln(is_sdhc ? "SDHC/SDXC" : "SDSC");

    /* 10. CMD2 — ALL_SEND_CID: move card to Identification state */
    r = send_cmd(2, 0, SD_CMD2_FLAGS, resp);
    if (r != SD_OK) return SD_ERR_INIT;

    /* 11. CMD3 — SEND_RELATIVE_ADDR: card publishes its RCA */
    r = send_cmd(3, 0, SD_CMD3_FLAGS, resp);
    if (r != SD_OK) return SD_ERR_INIT;
    card_rca = (resp[0] >> 16) & 0xFFFFu;
    uart_puts("  [SD] RCA: "); uart_puthex64(card_rca); uart_puts("\r\n");

    /* 12. Raise clock to data transfer speed (25 MHz) */
    sdhci_set_clock(25000000u);

    /* 13. CMD7 — SELECT_CARD: move card to Transfer state */
    r = send_cmd(7, (uint32_t)card_rca << 16, SD_CMD7_FLAGS, resp);
    if (r != SD_OK) return SD_ERR_INIT;

    /* 14. CMD16 — SET_BLOCKLEN: fix block size at 512 bytes (required for SDSC) */
    r = send_cmd(16, SD_BLOCK_SIZE, SD_CMD16_FLAGS, resp);
    if (r != SD_OK) return SD_ERR_INIT;

    /* 15. ACMD6 — SET_BUS_WIDTH: switch to 4-bit bus for higher throughput */
    r = send_acmd(6, 0x2u, SD_ACMD6_FLAGS, resp);
    if (r != SD_OK) {
        uart_putln("  [SD] 4-bit switch failed; staying at 1-bit");
    } else {
        /* Tell the SDHCI controller to use 4-bit mode */
        uint8_t hc = *r8(SDHCI_HOST_CTRL1);
        *r8(SDHCI_HOST_CTRL1) = (uint8_t)(hc | HCTRL1_4BIT);
        uart_putln("  [SD] 4-bit bus enabled");
    }

    uart_putln("  [SD] Init complete");
    return SD_OK;
}

/* ------------------------------------------------------------------ */
/* Block read                                                          */
/* ------------------------------------------------------------------ */

sd_result_t sd_read_blocks(uint32_t lba, uint8_t *buf, uint32_t count)
{
    if (count == 0) return SD_OK;

    /*
     * SDSC cards use byte addresses; SDHC/SDXC use sector (LBA) addresses.
     */
    uint32_t addr = is_sdhc ? lba : lba * SD_BLOCK_SIZE;

    /* Choose single- or multi-block read command */
    uint8_t  cmd_idx  = (count == 1u) ? 17u : 18u;
    uint16_t xfer     = XFER_READ | XFER_BLKCNT_EN;
    if (count > 1u)
        xfer |= XFER_MULTI_BLK | XFER_AUTOCMD12;

    /* Programme block count and size before issuing the command */
    *r16(SDHCI_BLKSIZE) = (uint16_t)SD_BLOCK_SIZE;
    *r16(SDHCI_BLKCNT)  = (uint16_t)count;
    *r16(SDHCI_TRANSFER_MODE) = xfer;

    /* Issue read command */
    sd_result_t r = send_cmd(cmd_idx, addr, SD_CMD17_FLAGS, NULL);
    if (r != SD_OK) return r;

    /* Read each block from the FIFO */
    for (uint32_t b = 0; b < count; b++) {

        /* Wait for Buffer Read Ready or Error (100 ms per block) */
        uint32_t timeout = 100000u;
        uint16_t st;
        do {
            st = *r16(SDHCI_INT_STATUS);
        } while (!(st & (INT_BUF_READ_READY | INT_ERROR)) && --timeout);

        if (!timeout || (st & INT_ERROR)) {
            uart_puts("  [SD] Read error at LBA "); uart_putu32(lba + b);
            uart_puts("\r\n");
            sdhci_reset(SW_RESET_DAT);
            return SD_ERR_READ;
        }
        *r16(SDHCI_INT_STATUS) = INT_BUF_READ_READY;

        /* Drain 512 bytes as 128 × 32-bit words */
        uint32_t *dst = (uint32_t *)(void *)(buf + b * SD_BLOCK_SIZE);
        for (int i = 0; i < (int)(SD_BLOCK_SIZE / 4u); i++)
            dst[i] = *r32(SDHCI_DATA);
    }

    /* Wait for Transfer Complete (max 500 ms) */
    uint32_t timeout = 500000u;
    uint16_t st;
    do {
        st = *r16(SDHCI_INT_STATUS);
    } while (!(st & (INT_XFER_COMPLETE | INT_ERROR)) && --timeout);

    *r16(SDHCI_INT_STATUS) = INT_XFER_COMPLETE;

    if (!timeout || (st & INT_ERROR))
        return SD_ERR_READ;

    return SD_OK;
}
