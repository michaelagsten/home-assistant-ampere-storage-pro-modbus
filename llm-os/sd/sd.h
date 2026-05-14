#pragma once

#include <stdint.h>
#include <stddef.h>

/*
 * SD card driver — public interface.
 *
 * Implements SD Specification v4.x initialization (identification,
 * RCA negotiation, high-speed switch, 4-bit bus) and block reads
 * via SDHCI polling (no DMA, no interrupts in phase 1).
 *
 * Supports SDSC (byte-addressed), SDHC and SDXC (sector-addressed).
 */

#define SD_BLOCK_SIZE  512u   /* Always 512 bytes per sector */

typedef enum {
    SD_OK            =  0,
    SD_ERR_NO_CARD   = -1,   /* No card detected in slot          */
    SD_ERR_TIMEOUT   = -2,   /* Command or data transfer timeout  */
    SD_ERR_INIT      = -3,   /* Card initialization failed        */
    SD_ERR_READ      = -4,   /* Block read failed                 */
} sd_result_t;

/*
 * Initialise the SDHCI controller and SD card.
 * Must complete successfully before calling sd_read_blocks().
 */
sd_result_t sd_init(void);

/*
 * Read one or more 512-byte blocks from the SD card.
 *
 * lba   — logical block address (sector number, 0-based)
 * buf   — destination buffer; must be at least count × 512 bytes
 * count — number of consecutive sectors to read
 */
sd_result_t sd_read_blocks(uint32_t lba, uint8_t *buf, uint32_t count);
