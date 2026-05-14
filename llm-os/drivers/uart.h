#pragma once

#include <stdint.h>
#include <stddef.h>

/*
 * Minimal PL011 UART driver for bare-metal RPi5.
 *
 * On RPi5, the 40-pin header serial port (GPIO 14 TX / GPIO 15 RX) is
 * controlled by the RP1 companion chip.  With "enable_uart=1" in config.txt
 * the GPU firmware configures the GPIO mux before kernel8.img is loaded,
 * so we only need to initialise the UART registers themselves.
 *
 * Baud rate: 115200 (matches the firmware default; adjust UART_CLOCK_HZ
 * in uart.c if your board reports a different UART reference clock).
 */

void uart_init(void);

void uart_putc(char c);
char uart_getc(void);

void uart_puts(const char *s);
void uart_putln(const char *s);

/* Formatted numeric output (no printf dependency) */
void uart_puthex64(uint64_t v);
void uart_putu32(uint32_t v);
void uart_puts_n(const char *s, size_t n);
