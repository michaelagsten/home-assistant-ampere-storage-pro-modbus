#pragma once

#include <stdint.h>
#include <stddef.h>

/*
 * FAT32 reader — interface.
 *
 * Provides the minimum needed to read a single large file (MODEL.GGUF)
 * from the first FAT32 partition on the SD card.
 *
 * On RPi5, the SD card is controlled by the RP1 chip's SDIO/EMMC
 * controller.  The implementation will target the RP1 SD host at:
 *   Physical base: 0x1F00060000  (RP1 EMMC / SD host)
 *
 * SD card protocol (SPI or native 4-bit SDIO):
 *   Phase 1 — CMD0 (reset), CMD8 (check voltage), ACMD41 (init)
 *   Phase 2 — CMD2 (CID), CMD3 (RCA), CMD7 (select), CMD16 (block size)
 *   Phase 3 — Read blocks via CMD17 / CMD18
 *
 * FAT32 on top:
 *   Read MBR → locate FAT32 partition → read BPB → walk directory tree
 *   → locate MODEL.GGUF → read all clusters into destination buffer
 *
 * NOTE: This is one of the most complex bare-metal drivers in the project.
 * The implementation in fat32.c will be built incrementally:
 *   Step A: SD card init + single-block read
 *   Step B: MBR / partition table parsing
 *   Step C: FAT32 BPB + cluster chain walking
 *   Step D: Directory listing + file open
 *   Step E: Large sequential read with progress reporting via UART
 */

typedef enum {
    FAT32_OK              =  0,
    FAT32_ERR_NO_CARD     = -1,
    FAT32_ERR_INIT_FAIL   = -2,
    FAT32_ERR_NO_FAT32    = -3,
    FAT32_ERR_NOT_FOUND   = -4,
    FAT32_ERR_TOO_LARGE   = -5,
    FAT32_ERR_READ_FAIL   = -6,
} fat32_result_t;

/*
 * Initialise the SD host controller and mount the first FAT32 partition.
 * Must be called before fat32_load_file().
 *
 * Returns FAT32_OK on success.
 */
fat32_result_t fat32_init(void);

/*
 * Load an entire file from the FAT32 root directory into dest.
 *
 * filename  — 8.3 uppercase name, e.g. "MODEL.GGUF"
 *             (long-filename support is not implemented; rename the
 *              file on a PC if needed)
 * dest      — destination buffer in RAM (should point to __model_base)
 * size_out  — set to actual file size in bytes on success
 *
 * Returns FAT32_OK on success.
 */
fat32_result_t fat32_load_file(const char *filename,
                               void *dest,
                               size_t *size_out);
