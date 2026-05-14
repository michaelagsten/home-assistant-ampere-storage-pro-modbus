#include "fat32.h"
#include "sd.h"
#include "../drivers/uart.h"

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/* On-disk structures (all little-endian; AArch64 default is LE)      */
/* ------------------------------------------------------------------ */

/*
 * MBR partition entry (16 bytes, located at offset 446 in sector 0).
 * FAT32 uses partition type 0x0B (CHS) or 0x0C (LBA).
 */
typedef struct {
    uint8_t  status;        /* 0x80 = bootable, 0x00 = not                */
    uint8_t  chs_first[3]; /* CHS of first sector (ignored; use LBA)      */
    uint8_t  type;          /* Partition type: 0x0B/0x0C = FAT32          */
    uint8_t  chs_last[3];  /* CHS of last sector (ignored)                */
    uint32_t lba_start;     /* First sector of partition                   */
    uint32_t lba_size;      /* Number of sectors in partition              */
} __attribute__((packed)) mbr_part_t;

/*
 * FAT32 BIOS Parameter Block (first 90 bytes of the partition's boot sector).
 */
typedef struct {
    uint8_t  jump[3];               /* 0x00: Jump to boot code             */
    uint8_t  oem_name[8];           /* 0x03: OEM identifier                */
    uint16_t bytes_per_sector;      /* 0x0B: Always 512 for us             */
    uint8_t  sectors_per_cluster;   /* 0x0D: Power of 2 (1–128)           */
    uint16_t reserved_sectors;      /* 0x0E: Sectors before first FAT      */
    uint8_t  fat_count;             /* 0x10: Number of FAT copies (2)      */
    uint16_t root_entry_count;      /* 0x11: 0 for FAT32                   */
    uint16_t total_sectors_16;      /* 0x13: 0 for FAT32 (>32 MB)         */
    uint8_t  media_type;            /* 0x15: 0xF8 for fixed disk           */
    uint16_t fat_size_16;           /* 0x16: 0 for FAT32                   */
    uint16_t sectors_per_track;     /* 0x18: CHS geometry (ignored)        */
    uint16_t heads;                 /* 0x1A: CHS geometry (ignored)        */
    uint32_t hidden_sectors;        /* 0x1C: Sectors before this partition  */
    uint32_t total_sectors_32;      /* 0x20: Total sectors in volume       */
    /* FAT32 extended BPB starts here */
    uint32_t fat_size_32;           /* 0x24: Sectors per FAT               */
    uint16_t ext_flags;             /* 0x28: Mirroring flags               */
    uint16_t fs_version;            /* 0x2A: Must be 0x0000                */
    uint32_t root_cluster;          /* 0x2C: First cluster of root dir     */
    uint16_t fs_info_sector;        /* 0x30: FSInfo sector number          */
    uint16_t backup_boot_sector;    /* 0x32: Backup boot sector            */
    uint8_t  reserved[12];          /* 0x34                                */
    uint8_t  drive_number;          /* 0x40                                */
    uint8_t  reserved2;             /* 0x41                                */
    uint8_t  boot_signature;        /* 0x42: 0x29 if following fields set  */
    uint32_t volume_id;             /* 0x43                                */
    uint8_t  volume_label[11];      /* 0x47                                */
    uint8_t  fs_type[8];            /* 0x52: "FAT32   "                    */
} __attribute__((packed)) fat32_bpb_t;

/*
 * FAT32 8.3 directory entry (32 bytes).
 * Long File Name (LFN) entries have attribute 0x0F and are skipped.
 */
typedef struct {
    uint8_t  name[8];       /* Filename, space-padded, uppercase            */
    uint8_t  ext[3];        /* Extension, space-padded, uppercase           */
    uint8_t  attributes;    /* 0x0F = LFN entry, 0x10 = directory          */
    uint8_t  reserved;
    uint8_t  create_tenth;
    uint16_t create_time;
    uint16_t create_date;
    uint16_t access_date;
    uint16_t cluster_high;  /* High 16 bits of first cluster                */
    uint16_t modify_time;
    uint16_t modify_date;
    uint16_t cluster_low;   /* Low 16 bits of first cluster                 */
    uint32_t file_size;     /* File size in bytes (0 for directories)       */
} __attribute__((packed)) fat32_dirent_t;

#define ATTR_LFN        0x0Fu
#define ATTR_DIRECTORY  0x10u
#define ATTR_VOLUME_ID  0x08u

#define FAT32_EOC       0x0FFFFFF8u  /* End of cluster chain                */
#define FAT32_FREE      0x00000000u
#define FAT32_MASK      0x0FFFFFFFu  /* Mask out upper 4 bits in FAT entry  */

/* ------------------------------------------------------------------ */
/* FAT32 volume state                                                  */
/* ------------------------------------------------------------------ */

static struct {
    uint32_t part_lba;              /* LBA of partition start               */
    uint32_t fat_lba;               /* LBA of first FAT                     */
    uint32_t data_lba;              /* LBA of data area (cluster 2)         */
    uint32_t root_cluster;          /* First cluster of root directory       */
    uint32_t sectors_per_cluster;
    uint32_t bytes_per_cluster;
} vol;

/* Re-usable 512-byte sector buffer */
static uint8_t s_buf[SD_BLOCK_SIZE];

/* ------------------------------------------------------------------ */
/* Internal helpers (no libc)                                         */
/* ------------------------------------------------------------------ */

static int mem_eq(const void *a, const void *b, size_t n)
{
    const uint8_t *p = (const uint8_t *)a;
    const uint8_t *q = (const uint8_t *)b;
    for (size_t i = 0; i < n; i++)
        if (p[i] != q[i]) return 0;
    return 1;
}

/* Convert 'A'-'Z','a'-'z' to uppercase */
static uint8_t upper(uint8_t c)
{
    return (c >= 'a' && c <= 'z') ? (uint8_t)(c - 32u) : c;
}

/*
 * Build the 11-byte FAT32 8.3 name from a null-terminated filename.
 *
 * "MODEL.GGUF" → "MODEL   " + "GUF" (11 bytes total, space-padded)
 * "BOOT.BIN"   → "BOOT    " + "BIN"
 *
 * Returns 0 on success, -1 if filename format is unrecognised.
 */
static int make_83(const char *filename, uint8_t out[11])
{
    /* Fill with spaces */
    for (int i = 0; i < 11; i++) out[i] = ' ';

    int i = 0, j = 0;
    /* Copy base name (max 8 chars) */
    while (filename[i] && filename[i] != '.' && j < 8) {
        out[j++] = upper((uint8_t)filename[i++]);
    }
    /* Skip the dot */
    if (filename[i] == '.') i++;
    /* Copy extension (max 3 chars) */
    int ej = 8;
    while (filename[i] && ej < 11) {
        out[ej++] = upper((uint8_t)filename[i++]);
    }
    return (filename[i] == '\0') ? 0 : -1;
}

/* ------------------------------------------------------------------ */
/* Cluster chain operations                                            */
/* ------------------------------------------------------------------ */

/*
 * Convert a cluster number to its starting LBA.
 * Clusters 0 and 1 are reserved; data starts at cluster 2.
 */
static uint32_t cluster_lba(uint32_t cluster)
{
    return vol.data_lba + (cluster - 2u) * vol.sectors_per_cluster;
}

/*
 * Read the FAT entry for a given cluster.
 * Returns the next cluster in the chain, or FAT32_EOC if end of file.
 */
static uint32_t fat_next(uint32_t cluster)
{
    /* Each FAT entry is 4 bytes; compute which sector holds this cluster */
    uint32_t fat_byte_offset = cluster * 4u;
    uint32_t sector = vol.fat_lba + fat_byte_offset / SD_BLOCK_SIZE;
    uint32_t offset = fat_byte_offset % SD_BLOCK_SIZE;

    if (sd_read_blocks(sector, s_buf, 1) != SD_OK)
        return FAT32_EOC;

    uint32_t entry;
    /* Safe unaligned read (offset may not be 4-byte aligned) */
    entry = (uint32_t)s_buf[offset]
          | ((uint32_t)s_buf[offset + 1] << 8)
          | ((uint32_t)s_buf[offset + 2] << 16)
          | ((uint32_t)s_buf[offset + 3] << 24);

    return entry & FAT32_MASK;
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

fat32_result_t fat32_init(void)
{
    /* 1. Initialise the SD card */
    sd_result_t sdr = sd_init();
    if (sdr == SD_ERR_NO_CARD) return FAT32_ERR_NO_CARD;
    if (sdr != SD_OK)           return FAT32_ERR_INIT_FAIL;

    /* 2. Read MBR (sector 0) */
    if (sd_read_blocks(0, s_buf, 1) != SD_OK)
        return FAT32_ERR_READ_FAIL;

    /* MBR signature check */
    if (s_buf[510] != 0x55u || s_buf[511] != 0xAAu) {
        uart_putln("  [FAT32] MBR signature invalid");
        return FAT32_ERR_NO_FAT32;
    }

    /* 3. Find the first FAT32 partition (type 0x0B or 0x0C) */
    const mbr_part_t *parts = (const mbr_part_t *)(s_buf + 446);
    vol.part_lba = 0;
    for (int i = 0; i < 4; i++) {
        if (parts[i].type == 0x0Bu || parts[i].type == 0x0Cu) {
            vol.part_lba = parts[i].lba_start;
            uart_puts("  [FAT32] Partition "); uart_putu32((uint32_t)i);
            uart_puts(" at LBA "); uart_putu32(vol.part_lba);
            uart_puts("\r\n");
            break;
        }
    }
    if (vol.part_lba == 0) {
        uart_putln("  [FAT32] No FAT32 partition found in MBR");
        return FAT32_ERR_NO_FAT32;
    }

    /* 4. Read the Volume Boot Record (BPB) */
    if (sd_read_blocks(vol.part_lba, s_buf, 1) != SD_OK)
        return FAT32_ERR_READ_FAIL;

    /* Boot sector signature */
    if (s_buf[510] != 0x55u || s_buf[511] != 0xAAu) {
        uart_putln("  [FAT32] VBR signature invalid");
        return FAT32_ERR_NO_FAT32;
    }

    const fat32_bpb_t *bpb = (const fat32_bpb_t *)s_buf;

    /* Sanity checks */
    if (bpb->bytes_per_sector != 512u) {
        uart_putln("  [FAT32] Non-512 sector size not supported");
        return FAT32_ERR_NO_FAT32;
    }
    if (bpb->fat_size_32 == 0u || bpb->sectors_per_cluster == 0u) {
        uart_putln("  [FAT32] BPB sanity check failed");
        return FAT32_ERR_NO_FAT32;
    }

    /* Compute key LBA values */
    vol.sectors_per_cluster = bpb->sectors_per_cluster;
    vol.bytes_per_cluster   = vol.sectors_per_cluster * SD_BLOCK_SIZE;
    vol.root_cluster        = bpb->root_cluster;

    vol.fat_lba  = vol.part_lba + bpb->reserved_sectors;
    vol.data_lba = vol.fat_lba
                 + (uint32_t)bpb->fat_count * bpb->fat_size_32;

    uart_puts("  [FAT32] FAT  LBA: "); uart_putu32(vol.fat_lba);  uart_puts("\r\n");
    uart_puts("  [FAT32] Data LBA: "); uart_putu32(vol.data_lba); uart_puts("\r\n");
    uart_puts("  [FAT32] Cluster:  "); uart_putu32(vol.sectors_per_cluster);
    uart_puts(" sectors = "); uart_putu32(vol.bytes_per_cluster); uart_putln(" bytes");
    uart_puts("  [FAT32] Root cluster: "); uart_putu32(vol.root_cluster); uart_puts("\r\n");

    return FAT32_OK;
}

/* ------------------------------------------------------------------ */

fat32_result_t fat32_load_file(const char *filename,
                               void *dest,
                               size_t *size_out)
{
    /* Build the 11-byte 8.3 uppercase name to search for */
    uint8_t target[11];
    if (make_83(filename, target) < 0) {
        uart_puts("  [FAT32] Bad filename: "); uart_putln(filename);
        return FAT32_ERR_NOT_FOUND;
    }

    uart_puts("  [FAT32] Looking for: ");
    for (int i = 0; i < 11; i++) uart_putc((char)target[i]);
    uart_puts("\r\n");

    /* ---- Walk the root directory cluster chain ---- */
    uint32_t dir_cluster = vol.root_cluster;
    uint32_t file_cluster = 0;
    uint32_t file_size    = 0;
    int      found        = 0;

    while (!found && dir_cluster < FAT32_EOC) {
        uint32_t lba = cluster_lba(dir_cluster);

        for (uint32_t s = 0; s < vol.sectors_per_cluster && !found; s++) {
            if (sd_read_blocks(lba + s, s_buf, 1) != SD_OK)
                return FAT32_ERR_READ_FAIL;

            const fat32_dirent_t *entry = (const fat32_dirent_t *)s_buf;
            int entries_per_sector = (int)(SD_BLOCK_SIZE / sizeof(fat32_dirent_t));

            for (int e = 0; e < entries_per_sector; e++, entry++) {
                uint8_t first = entry->name[0];

                if (first == 0x00u) goto search_done;   /* End of directory */
                if (first == 0xE5u) continue;            /* Deleted entry    */
                if (entry->attributes == ATTR_LFN)  continue;  /* LFN entry */
                if (entry->attributes &  ATTR_VOLUME_ID) continue;
                if (entry->attributes &  ATTR_DIRECTORY) continue;

                /* Compare 8.3 name (name[8] + ext[3] = 11 bytes) */
                uint8_t entry_name[11];
                for (int k = 0; k < 8;  k++) entry_name[k]   = entry->name[k];
                for (int k = 0; k < 3;  k++) entry_name[8+k] = entry->ext[k];

                if (mem_eq(entry_name, target, 11)) {
                    file_cluster = ((uint32_t)entry->cluster_high << 16)
                                 |  (uint32_t)entry->cluster_low;
                    file_size    = entry->file_size;
                    found = 1;
                    break;
                }
            }
        }

        dir_cluster = fat_next(dir_cluster);
    }

search_done:
    if (!found) {
        uart_puts("  [FAT32] File not found: "); uart_putln(filename);
        return FAT32_ERR_NOT_FOUND;
    }

    uart_puts("  [FAT32] Found: cluster="); uart_putu32(file_cluster);
    uart_puts(", size="); uart_putu32(file_size); uart_puts(" bytes\r\n");

    /* ---- Load file data following the cluster chain ---- */
    uint8_t *dst       = (uint8_t *)dest;
    uint32_t remaining = file_size;
    uint32_t cluster   = file_cluster;
    uint32_t loaded    = 0;

    /* Progress reporting: print a dot every 8 MB */
    uint32_t progress_step = 8u * 1024u * 1024u;
    uint32_t next_progress = progress_step;
    uart_puts("  [FAT32] Loading");

    while (remaining > 0 && cluster >= 2u && cluster < FAT32_EOC) {
        uint32_t lba    = cluster_lba(cluster);
        uint32_t bytes  = (remaining < vol.bytes_per_cluster)
                        ? remaining : vol.bytes_per_cluster;
        uint32_t sects  = (bytes + SD_BLOCK_SIZE - 1u) / SD_BLOCK_SIZE;

        if (sd_read_blocks(lba, dst, sects) != SD_OK) {
            uart_puts("\r\n  [FAT32] Read error at cluster ");
            uart_putu32(cluster); uart_puts("\r\n");
            return FAT32_ERR_READ_FAIL;
        }

        dst       += bytes;
        loaded    += bytes;
        remaining -= bytes;

        if (loaded >= next_progress) {
            uart_putc('.');
            next_progress += progress_step;
        }

        cluster = fat_next(cluster);
    }

    uart_puts("\r\n  [FAT32] Loaded "); uart_putu32(loaded);
    uart_putln(" bytes OK");

    if (size_out) *size_out = (size_t)file_size;
    return FAT32_OK;
}
