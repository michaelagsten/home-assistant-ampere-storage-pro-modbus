#include <stdint.h>
#include <stddef.h>

#include "../drivers/uart.h"
#include "mm.h"
#include "../llm/gguf.h"
#include "../llm/tokenizer.h"
#include "../llm/transformer.h"
#include "../sd/fat32.h"
#include "../shell/shell.h"

/* Symbols exported by the linker script (boot/linker.ld) */
extern uint8_t __heap_start[];
extern uint8_t __heap_end[];
extern uint8_t __model_base[];

/* ------------------------------------------------------------------ */

static const char BANNER[] =
    "\r\n"
    "  ██╗     ██╗     ███╗   ███╗      ██████╗ ███████╗\r\n"
    "  ██║     ██║     ████╗ ████║     ██╔═══██╗██╔════╝\r\n"
    "  ██║     ██║     ██╔████╔██║     ██║   ██║███████╗\r\n"
    "  ██║     ██║     ██║╚██╔╝██║     ██║   ██║╚════██║\r\n"
    "  ███████╗███████╗██║ ╚═╝ ██║     ╚██████╔╝███████║\r\n"
    "  ╚══════╝╚══════╝╚═╝     ╚═╝      ╚═════╝ ╚══════╝\r\n"
    "\r\n"
    "  Natural Language OS  |  Raspberry Pi 5  |  Bare Metal AArch64\r\n"
    "  No Linux. No dependencies. Just silicon and language.\r\n"
    "\r\n";

/* ------------------------------------------------------------------ */

static void boot_ok(const char *label)
{
    uart_puts("  [ OK ] ");
    uart_putln(label);
}

static void boot_fail(const char *label)
{
    uart_puts("  [FAIL] ");
    uart_putln(label);
}

/* ------------------------------------------------------------------ */

void kernel_main(void)
{
    /* ---- UART must be first — nothing works without it ------------ */
    uart_init();
    uart_puts(BANNER);

    /* ---- Heap ----------------------------------------------------- */
    uart_putln("Boot sequence:");
    size_t heap_bytes = (size_t)(__heap_end - __heap_start);
    mm_init(__heap_start, heap_bytes);
    uart_puts("  [ OK ] Heap  ");
    uart_putu32((uint32_t)(heap_bytes >> 20));
    uart_putln(" MB");

    /* ---- SD card + FAT32 ----------------------------------------- */
    uart_puts("  [    ] SD / FAT32 driver ... ");
    fat32_result_t sd_res = fat32_init();
    if (sd_res == FAT32_OK) {
        boot_ok("SD card mounted");
    } else {
        boot_fail("SD card not found (model must be on SD card)");
        /* Non-fatal: drop to interactive shell anyway */
    }

    /* ---- Load GGUF model ----------------------------------------- */
    gguf_model_t model;
    int model_loaded = 0;

    if (sd_res == FAT32_OK) {
        uart_puts("  [    ] Loading model weights ... ");
        size_t model_size = 0;
        fat32_result_t load_res = fat32_load_file(
            "MODEL.GGUF",
            (void *)__model_base,
            &model_size
        );

        if (load_res == FAT32_OK && gguf_load(__model_base, model_size, &model) == 0) {
            boot_ok("Model loaded");
            uart_puts("         n_layer="); uart_putu32(model.n_layer);
            uart_puts("  n_embd=");         uart_putu32(model.n_embd);
            uart_puts("  n_vocab=");        uart_putu32(model.n_vocab);
            uart_puts("\r\n");
            model_loaded = 1;
        } else {
            boot_fail("Model load failed (check MODEL.GGUF on SD card)");
        }
    }

    /* ---- Tokenizer ----------------------------------------------- */
    tokenizer_t tokenizer;
    int tok_ready = 0;

    if (model_loaded) {
        uart_puts("  [    ] Initialising tokenizer ... ");
        if (tokenizer_init(&tokenizer, model.vocab_data, model.vocab_data_size) == 0) {
            boot_ok("Tokenizer ready");
            tok_ready = 1;
        } else {
            boot_fail("Tokenizer init failed");
        }
    }

    /* ---- Transformer KV-cache ------------------------------------ */
    transformer_t transformer;
    int xfmr_ready = 0;

    if (model_loaded && tok_ready) {
        uart_puts("  [    ] Allocating KV-cache ... ");
        if (transformer_init(&transformer, &model, &tokenizer) == 0) {
            boot_ok("Transformer ready");
            xfmr_ready = 1;
        } else {
            boot_fail("Transformer init failed (out of memory?)");
        }
    }

    /* ---- Shell --------------------------------------------------- */
    uart_puts("\r\n");
    if (xfmr_ready) {
        uart_putln("All systems nominal. Entering natural language shell.");
        shell_run(&transformer);
    } else {
        uart_putln("Running in echo mode (model not loaded).");
        shell_run((void *)0);
    }

    /* kernel_main must never return — halt if it somehow does */
    for (;;)
        __asm__ volatile("wfe");
}
