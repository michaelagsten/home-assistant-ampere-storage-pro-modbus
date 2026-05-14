#include "shell.h"
#include "../drivers/uart.h"
#include "../kernel/mm.h"

#include <stdint.h>
#include <stddef.h>

#define INPUT_MAX       512u
#define DEFAULT_TOKENS  256u
#define DEFAULT_TEMP    0.8f

/* ------------------------------------------------------------------ */
/* Minimal string helpers (no libc available)                          */
/* ------------------------------------------------------------------ */

static size_t s_len(const char *s)
{
    size_t n = 0;
    while (s[n]) n++;
    return n;
}

static int s_starts(const char *s, const char *prefix)
{
    while (*prefix) {
        if (*s++ != *prefix++) return 0;
    }
    return 1;
}

/* Parse a simple unsigned integer from a string */
static uint32_t s_atou(const char *s)
{
    while (*s == ' ') s++;
    uint32_t v = 0;
    while (*s >= '0' && *s <= '9')
        v = v * 10u + (uint32_t)(*s++ - '0');
    return v;
}

/* Parse a float from a string (digits.digits only, no exponent) */
static float s_atof(const char *s)
{
    while (*s == ' ') s++;
    float v = 0.0f, frac = 0.1f;
    int in_frac = 0;
    while ((*s >= '0' && *s <= '9') || *s == '.') {
        if (*s == '.') { in_frac = 1; s++; continue; }
        if (!in_frac) v = v * 10.0f + (float)(*s - '0');
        else        { v += frac * (float)(*s - '0'); frac *= 0.1f; }
        s++;
    }
    return v;
}

/* ------------------------------------------------------------------ */
/* UART line editor                                                    */
/* ------------------------------------------------------------------ */

static size_t readline(char *buf, size_t max)
{
    size_t i = 0;
    for (;;) {
        char c = uart_getc();

        if (c == '\r' || c == '\n') {
            uart_puts("\r\n");
            break;
        }

        /* Backspace / DEL */
        if ((c == '\x7F' || c == '\x08') && i > 0) {
            i--;
            uart_puts("\b \b");
            continue;
        }

        /* Ctrl-C → discard line */
        if (c == '\x03') {
            uart_puts("^C\r\n");
            buf[0] = '\0';
            return 0;
        }

        if (i < max - 1) {
            buf[i++] = c;
            uart_putc(c);   /* local echo */
        }
    }
    buf[i] = '\0';
    return i;
}

/* ------------------------------------------------------------------ */
/* Token streaming callback                                            */
/* ------------------------------------------------------------------ */

static void stream_token(const char *text, void *user_data)
{
    (void)user_data;
    uart_puts(text);
}

/* ------------------------------------------------------------------ */
/* Built-in command dispatch                                           */
/* ------------------------------------------------------------------ */

static void cmd_info(transformer_t *t)
{
    uart_putln("--- System info ---");
    uart_puts("  Heap used:      "); uart_putu32((uint32_t)(mm_used()      >> 10)); uart_putln(" KB");
    uart_puts("  Heap available: "); uart_putu32((uint32_t)(mm_available() >> 10)); uart_putln(" KB");

    if (t && t->model) {
        const gguf_model_t *m = t->model;
        uart_puts("  Model arch:     "); uart_putln(m->arch);
        uart_puts("  n_layer:        "); uart_putu32(m->n_layer); uart_puts("\r\n");
        uart_puts("  n_embd:         "); uart_putu32(m->n_embd);  uart_puts("\r\n");
        uart_puts("  n_head:         "); uart_putu32(m->n_head);  uart_puts("\r\n");
        uart_puts("  n_vocab:        "); uart_putu32(m->n_vocab); uart_puts("\r\n");
        uart_puts("  Context pos:    "); uart_putu32(t->pos);      uart_puts("\r\n");
    } else {
        uart_putln("  No model loaded.");
    }
    uart_putln("-------------------");
}

/* ------------------------------------------------------------------ */
/* Main shell loop                                                     */
/* ------------------------------------------------------------------ */

void shell_run(transformer_t *t)
{
    char     buf[INPUT_MAX];
    float    temperature  = DEFAULT_TEMP;
    uint32_t max_tokens   = DEFAULT_TOKENS;

    if (t) {
        uart_putln("Natural language shell ready.");
        uart_putln("Built-in commands: /reset /temp <f> /tokens <n> /info /halt");
    } else {
        uart_putln("Echo mode (no model loaded). Built-in: /info /halt");
    }
    uart_puts("\r\n");

    for (;;) {
        uart_puts("> ");
        size_t len = readline(buf, INPUT_MAX);

        if (len == 0)
            continue;

        /* ---------- Built-in commands (prefixed with '/') ---------- */

        if (buf[0] == '/') {
            if (s_starts(buf, "/reset")) {
                if (t) { transformer_reset(t); uart_putln("Context cleared."); }
                else     uart_putln("No model to reset.");

            } else if (s_starts(buf, "/temp ")) {
                temperature = s_atof(buf + 6);
                uart_puts("Temperature set to: ");
                /* Print float with one decimal (simple approach) */
                uart_putu32((uint32_t)temperature);
                uart_putc('.');
                uart_putu32((uint32_t)((temperature - (float)(uint32_t)temperature) * 10.0f));
                uart_puts("\r\n");

            } else if (s_starts(buf, "/tokens ")) {
                max_tokens = s_atou(buf + 8);
                uart_puts("Max tokens set to: ");
                uart_putu32(max_tokens);
                uart_puts("\r\n");

            } else if (s_starts(buf, "/info")) {
                cmd_info(t);

            } else if (s_starts(buf, "/halt")) {
                uart_putln("Halting CPU. Goodbye.");
                for (;;) __asm__ volatile("wfe");

            } else {
                uart_puts("Unknown command: ");
                uart_putln(buf);
            }
            continue;
        }

        /* ---------- Natural language input → LLM ------------------- */

        if (t) {
            uart_puts("\r\n");
            int n = transformer_generate(t, buf, max_tokens,
                                         temperature, stream_token, (void *)0);
            uart_puts("\r\n\r\n");
            (void)n;
        } else {
            uart_puts("[echo] ");
            uart_puts(buf);
            uart_puts("\r\n");
        }
    }
}
