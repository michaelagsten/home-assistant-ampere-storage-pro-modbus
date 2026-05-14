/*
 * linker.ld — Memory layout for bare-metal RPi5 LLM-OS
 *
 * Physical memory map (RPi5, 8 GB variant):
 *   0x00000000 - 0x0007FFFF   Low memory / stack (512 KB)
 *   0x00080000 - ...          Kernel code + data  ← we load here
 *   (after BSS)               1 MB stack
 *   (after stack)             64 MB heap  (metadata, KV-cache, runtime state)
 *   0x100000000 and above     Model weights — loaded from SD card by FAT32 driver
 *
 * The GPU firmware (start4.elf) expects a raw AArch64 binary named
 * kernel8.img loaded at 0x80000.
 */

ENTRY(_start)

SECTIONS {
    . = 0x80000;

    /*----------------------------------------------------------------*/
    /* Code                                                            */
    /*----------------------------------------------------------------*/
    .text : {
        KEEP(*(.text.boot))     /* startup.S must be first */
        *(.text .text.*)
    }

    /*----------------------------------------------------------------*/
    /* Read-only data                                                  */
    /*----------------------------------------------------------------*/
    .rodata : ALIGN(8) {
        *(.rodata .rodata.*)
    }

    /*----------------------------------------------------------------*/
    /* Initialised data                                                */
    /*----------------------------------------------------------------*/
    .data : ALIGN(8) {
        *(.data .data.*)
    }

    /*----------------------------------------------------------------*/
    /* Zero-initialised data (BSS)                                     */
    /* startup.S zeroes [__bss_start, __bss_end) in 16-byte steps,    */
    /* so both symbols must be 16-byte aligned.                        */
    /*----------------------------------------------------------------*/
    . = ALIGN(16);
    __bss_start = .;
    .bss (NOLOAD) : {
        *(.bss .bss.*)
        *(COMMON)
    }
    . = ALIGN(16);
    __bss_end = .;

    /*----------------------------------------------------------------*/
    /* Stack — 1 MB, grows downward from _stack_top                   */
    /*----------------------------------------------------------------*/
    . = ALIGN(4096);
    __stack_bottom = .;
    . += 0x100000;              /* 1 MB */
    _stack_top = .;

    /*----------------------------------------------------------------*/
    /* Heap — 64 MB managed by mm.c bump allocator                    */
    /* Used for: tokenizer vocab, attention KV-cache, runtime structs  */
    /*----------------------------------------------------------------*/
    . = ALIGN(4096);
    __heap_start = .;
    . += 0x4000000;             /* 64 MB */
    __heap_end = .;

    /*----------------------------------------------------------------*/
    /* Model weight area marker — FAT32 loader places weights here     */
    /* Everything from __model_base onward is available for the model. */
    /*----------------------------------------------------------------*/
    . = ALIGN(4096);
    __model_base = .;
}
