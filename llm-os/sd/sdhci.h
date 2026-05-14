#pragma once

#include <stdint.h>

/*
 * SDHCI (SD Host Controller Interface) register map — Specification v3.0
 *
 * Used by the BCM2712 internal EMMC2 controller on Raspberry Pi 5.
 * The SD card slot on the RPi5 board connects to BCM2712 EMMC2, which
 * is an SDHCI-compatible controller on the SoC's internal AXI bus.
 *
 * Physical base address:
 *   BCM2712 EMMC2 (SD card slot): 0x1000D0000
 *
 * To verify on Raspberry Pi OS before going bare-metal:
 *   sudo cat /proc/iomem | grep -i mmc
 *
 * Note: The RP1 companion chip also has an EMMC controller at 0x1F00060000
 * (accessible via PCIe), but the SD card slot uses BCM2712 EMMC2 directly.
 */
#define SDHOST_BASE  0x1000D0000ULL

/* ------------------------------------------------------------------ */
/* Register offsets                                                    */
/* ------------------------------------------------------------------ */

#define SDHCI_ARG2              0x00u  /* ADMA System Address / Argument 2  */
#define SDHCI_BLKSIZE           0x04u  /* Block Size Register (16-bit)       */
#define SDHCI_BLKCNT            0x06u  /* Block Count Register (16-bit)      */
#define SDHCI_ARG1              0x08u  /* Argument 1                         */
#define SDHCI_TRANSFER_MODE     0x0Cu  /* Transfer Mode (16-bit)             */
#define SDHCI_COMMAND           0x0Eu  /* Command Register (16-bit)          */
#define SDHCI_RESPONSE0         0x10u  /* Response [31:0]                    */
#define SDHCI_RESPONSE1         0x14u  /* Response [63:32]                   */
#define SDHCI_RESPONSE2         0x18u  /* Response [95:64]                   */
#define SDHCI_RESPONSE3         0x1Cu  /* Response [127:96]                  */
#define SDHCI_DATA              0x20u  /* Buffer Data Port (32-bit reads)    */
#define SDHCI_PRESENT_STATE     0x24u  /* Present State (32-bit, read-only)  */
#define SDHCI_HOST_CTRL1        0x28u  /* Host Control 1 (8-bit)             */
#define SDHCI_POWER_CTRL        0x29u  /* Power Control (8-bit)              */
#define SDHCI_CLK_CTRL          0x2Cu  /* Clock Control (16-bit)             */
#define SDHCI_TIMEOUT_CTRL      0x2Eu  /* Timeout Control (8-bit)            */
#define SDHCI_SW_RESET          0x2Fu  /* Software Reset (8-bit)             */
#define SDHCI_INT_STATUS        0x30u  /* Normal Interrupt Status (16-bit)   */
#define SDHCI_ERR_STATUS        0x32u  /* Error Interrupt Status (16-bit)    */
#define SDHCI_INT_ENABLE        0x34u  /* Normal Interrupt Status Enable     */
#define SDHCI_ERR_ENABLE        0x36u  /* Error Interrupt Status Enable      */
#define SDHCI_HOST_CTRL2        0x3Eu  /* Host Control 2 (16-bit)            */
#define SDHCI_CAPABILITIES0     0x40u  /* Capabilities [31:0]                */
#define SDHCI_CAPABILITIES1     0x44u  /* Capabilities [63:32]               */
#define SDHCI_HOST_VERSION      0xFEu  /* Host Controller Version (16-bit)   */

/* ------------------------------------------------------------------ */
/* Present State (0x24) bits                                           */
/* ------------------------------------------------------------------ */
#define PSTATE_CMD_INHIBIT      (1u << 0)   /* CMD line busy (cmd in progress) */
#define PSTATE_DAT_INHIBIT      (1u << 1)   /* DAT line busy (data in progress)*/
#define PSTATE_BUF_READ_EN      (1u << 11)  /* Buffer read enable              */
#define PSTATE_BUF_WRITE_EN     (1u << 10)  /* Buffer write enable             */
#define PSTATE_CARD_INSERTED    (1u << 16)  /* Card detected in slot           */
#define PSTATE_CARD_STABLE      (1u << 17)  /* Card detect pin stable          */

/* ------------------------------------------------------------------ */
/* Normal Interrupt Status (0x30) bits                                 */
/* ------------------------------------------------------------------ */
#define INT_CMD_COMPLETE        (1u << 0)   /* Command complete                */
#define INT_XFER_COMPLETE       (1u << 1)   /* Transfer complete               */
#define INT_BUF_WRITE_READY     (1u << 4)   /* Buffer write ready              */
#define INT_BUF_READ_READY      (1u << 5)   /* Buffer read ready               */
#define INT_CARD_INSERTED       (1u << 6)   /* Card inserted                   */
#define INT_CARD_REMOVED        (1u << 7)   /* Card removed                    */
#define INT_ERROR               (1u << 15)  /* Error interrupt                 */
#define INT_ALL                 0xFFFFu

/* ------------------------------------------------------------------ */
/* Software Reset (0x2F) bits                                          */
/* ------------------------------------------------------------------ */
#define SW_RESET_ALL            (1u << 0)
#define SW_RESET_CMD            (1u << 1)
#define SW_RESET_DAT            (1u << 2)

/* ------------------------------------------------------------------ */
/* Clock Control (0x2C) bits                                           */
/* ------------------------------------------------------------------ */
#define CLK_INT_EN              (1u << 0)   /* Internal clock enable           */
#define CLK_INT_STABLE          (1u << 1)   /* Internal clock stable           */
#define CLK_SDCLK_EN            (1u << 2)   /* SD clock output enable          */

/*
 * Bits [15:8]: SDCLK Frequency Select (8-bit divider mode, SDHCI 2.0)
 * SD clock = Base clock / (2 × N).  N = 0 means divide-by-1 (= base clock).
 */
#define CLK_DIV(n)              (((uint16_t)(n) & 0xFFu) << 8)

/* ------------------------------------------------------------------ */
/* Power Control (0x29) bits                                           */
/* ------------------------------------------------------------------ */
#define PWR_ON                  (1u << 0)
#define PWR_330V                (0x7u << 1)  /* 3.3 V bus voltage              */

/* ------------------------------------------------------------------ */
/* Host Control 1 (0x28) bits                                          */
/* ------------------------------------------------------------------ */
#define HCTRL1_4BIT             (1u << 1)   /* 4-bit data bus width           */
#define HCTRL1_HISPEED          (1u << 2)   /* High Speed mode                */

/* ------------------------------------------------------------------ */
/* Transfer Mode (0x0C) bits                                           */
/* ------------------------------------------------------------------ */
#define XFER_BLKCNT_EN          (1u << 1)   /* Block count enable             */
#define XFER_AUTOCMD12          (1u << 2)   /* Auto CMD12 after multi-block   */
#define XFER_READ               (1u << 4)   /* 1 = host reads from card       */
#define XFER_MULTI_BLK          (1u << 5)   /* Multi-block transfer           */

/* ------------------------------------------------------------------ */
/* Command Register (0x0E) encoding                                    */
/* ------------------------------------------------------------------ */

/* Response type field [1:0] */
#define CMD_RESP_NONE           0x00u   /* No response                        */
#define CMD_RESP_136            0x01u   /* R2: 136-bit response               */
#define CMD_RESP_48             0x02u   /* R1, R3, R6, R7: 48-bit            */
#define CMD_RESP_48_BUSY        0x03u   /* R1b: 48-bit + busy check           */

#define CMD_CRC_EN              (1u << 3)  /* CRC check enable                */
#define CMD_IDX_EN              (1u << 4)  /* Command index check enable      */
#define CMD_DATA_PRESENT        (1u << 5)  /* Data transfer follows command   */
#define CMD_TYPE_ABORT          (3u << 6)  /* CMD12 / CMD52 abort type        */
#define CMD_INDEX(n)            ((uint16_t)((n) << 8))

/* Convenience macro: compose a full command register value */
#define MAKE_CMD(idx, flags)    (CMD_INDEX(idx) | (uint16_t)(flags))

/* ------------------------------------------------------------------ */
/* Capabilities[31:0] (0x40) — base clock frequency field             */
/* ------------------------------------------------------------------ */
#define CAP0_BASE_CLK_MASK      0x00003F00u  /* bits [13:8] in SDHCI 2.0     */
#define CAP0_BASE_CLK_SHIFT     8u

/* ------------------------------------------------------------------ */
/* SD card command shortcuts                                           */
/* ------------------------------------------------------------------ */
#define SD_CMD0_FLAGS   (CMD_RESP_NONE)
#define SD_CMD2_FLAGS   (CMD_RESP_136 | CMD_CRC_EN)
#define SD_CMD3_FLAGS   (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN)
#define SD_CMD7_FLAGS   (CMD_RESP_48_BUSY | CMD_CRC_EN | CMD_IDX_EN)
#define SD_CMD8_FLAGS   (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN)
#define SD_CMD12_FLAGS  (CMD_RESP_48_BUSY | CMD_CRC_EN | CMD_IDX_EN | CMD_TYPE_ABORT)
#define SD_CMD16_FLAGS  (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN)
#define SD_CMD17_FLAGS  (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN | CMD_DATA_PRESENT)
#define SD_CMD18_FLAGS  (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN | CMD_DATA_PRESENT)
#define SD_CMD55_FLAGS  (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN)
#define SD_ACMD6_FLAGS  (CMD_RESP_48  | CMD_CRC_EN | CMD_IDX_EN)
#define SD_ACMD41_FLAGS (CMD_RESP_48)   /* R3: no CRC or index check        */
