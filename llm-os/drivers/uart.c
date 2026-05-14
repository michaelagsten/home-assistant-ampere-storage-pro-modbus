#include "uart.h"

/*
 * RPi5 UART base address.
 *
 * The RPi5 routes GPIO14/15 through the RP1 companion chip (connected via
 * PCIe to the BCM2712 SoC).  The RP1's UART0 (PL011-compatible) is mapped
 * at physical address 0x1F00030000.
 *
 * The GPU firmware initialises the PCIe bridge and the RP1 before handing
 * off to kernel8.img, so this address is accessible from bare-metal code
 * without any additional PCIe setup on our part.
 *
 * If you see no output, cross-check with:
 *   sudo cat /proc/iomem | grep -i uart    (on Raspberry Pi OS)
 * and update UART_BASE accordingly.
 *
 * Alternative for BCM2712 internal UART0: 0x107D050000ULL
 */
#define UART_BASE       0x1F00030000ULL

/*
 * Reference clock fed to the RP1 UART.
 * The firmware configures the UART at 115200 baud before we run; we
 * re-initialise below using the same rate so output survives our init.
 *
 * If baud rate is wrong (garbled output) try: 48000000, 100000000, 200000000
 */
#define UART_CLOCK_HZ   50000000UL
#define UART_BAUD       115200UL

/* PL011 register offsets (byte-addressed, each register is 32-bit wide) */
#define DR      0x000   /* Data register (TX/RX) */
#define FR      0x018   /* Flag register */
#define IBRD    0x024   /* Integer baud-rate divisor */
#define FBRD    0x028   /* Fractional baud-rate divisor */
#define LCRH    0x02C   /* Line control */
#define CR      0x030   /* Control */
#define ICR     0x044   /* Interrupt clear */

/* FR bits */
#define FR_TXFF (1u << 5)   /* TX FIFO full  */
#define FR_RXFE (1u << 4)   /* RX FIFO empty */
#define FR_BUSY (1u << 3)   /* UART busy     */

/* CR bits */
#define CR_UARTEN (1u << 0)
#define CR_TXE    (1u << 8)
#define CR_RXE    (1u << 9)

/* LCRH bits */
#define LCRH_FEN        (1u << 4)   /* FIFO enable */
#define LCRH_WLEN_8BIT  (3u << 5)   /* 8-bit words */

static volatile uint32_t *reg(uint32_t offset)
{
    return (volatile uint32_t *)(UART_BASE + offset);
}

void uart_init(void)
{
    /* 1. Disable UART and wait for any current byte to finish */
    *reg(CR) = 0;
    while (*reg(FR) & FR_BUSY)
        ;

    /* 2. Set baud rate: divisor = UART_CLOCK_HZ / (16 * UART_BAUD)    */
    /*    Integer part stored in IBRD, fractional part (×64) in FBRD.  */
    uint32_t ibrd = UART_CLOCK_HZ / (16u * UART_BAUD);
    uint32_t fbrd = ((UART_CLOCK_HZ % (16u * UART_BAUD)) * 64u
                     + UART_BAUD / 2u) / UART_BAUD;
    *reg(IBRD) = ibrd;
    *reg(FBRD) = fbrd;

    /* 3. 8N1 + FIFO enable (LCRH must be written AFTER IBRD/FBRD) */
    *reg(LCRH) = LCRH_WLEN_8BIT | LCRH_FEN;

    /* 4. Clear all pending interrupts */
    *reg(ICR) = 0x7FFu;

    /* 5. Enable UART, TX, RX */
    *reg(CR) = CR_UARTEN | CR_TXE | CR_RXE;
}

void uart_putc(char c)
{
    while (*reg(FR) & FR_TXFF)
        ;
    *reg(DR) = (uint32_t)(unsigned char)c;
}

char uart_getc(void)
{
    while (*reg(FR) & FR_RXFE)
        ;
    return (char)(*reg(DR) & 0xFFu);
}

void uart_puts(const char *s)
{
    while (*s) {
        if (*s == '\n')
            uart_putc('\r');
        uart_putc(*s++);
    }
}

void uart_puts_n(const char *s, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (s[i] == '\n')
            uart_putc('\r');
        uart_putc(s[i]);
    }
}

void uart_putln(const char *s)
{
    uart_puts(s);
    uart_puts("\n");
}

void uart_puthex64(uint64_t v)
{
    const char hex[] = "0123456789abcdef";
    uart_puts("0x");
    for (int shift = 60; shift >= 0; shift -= 4)
        uart_putc(hex[(v >> shift) & 0xFu]);
}

void uart_putu32(uint32_t v)
{
    char buf[11];
    int  i = 10;
    buf[10] = '\0';
    if (v == 0) {
        uart_putc('0');
        return;
    }
    while (v) {
        buf[--i] = '0' + (char)(v % 10u);
        v /= 10u;
    }
    uart_puts(&buf[i]);
}
