# ============================================================
#  LLM-OS — Bare-Metal Makefile for Raspberry Pi 5 (AArch64)
# ============================================================
#
# Requirements (install on Linux/macOS build host):
#   sudo apt install gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu
#   -- or on macOS: brew install aarch64-elf-gcc
#
# Usage:
#   make          — build kernel8.img
#   make clean    — remove all build artefacts
#
# Flashing:
#   Copy the following files to the FAT32 boot partition of a microSD card:
#     config.txt
#     kernel8.img
#   Also copy your quantised GGUF model as MODEL.GGUF to the same partition.
#   (Download e.g. TinyLlama-1.1B-Chat-v1.0.Q4_0.gguf and rename it.)
# ============================================================

CROSS   ?= aarch64-linux-gnu

CC      := $(CROSS)-gcc
LD      := $(CROSS)-ld
OBJCOPY := $(CROSS)-objcopy
OBJDUMP := $(CROSS)-objdump

# -mcpu=cortex-a76    : RPi5 CPU (BCM2712 uses Cortex-A76 cores)
# -ffreestanding      : no hosted C runtime; GCC freestanding headers available
# -nostdlib           : do not link against libc / libgcc startup files
# -mstrict-align      : no unaligned memory access (safer on AArch64 bare-metal)
# -fno-stack-protector: no __stack_chk_guard (we have no libc to provide it)
# -fno-builtin        : do not silently replace e.g. memcpy with a library call
# -O2                 : optimise — important for inference performance on RPi5

CFLAGS := \
    -mcpu=cortex-a76        \
    -ffreestanding          \
    -nostdlib               \
    -mstrict-align          \
    -fno-stack-protector    \
    -fno-builtin            \
    -fno-common             \
    -O2                     \
    -Wall -Wextra           \
    -Wno-unused-parameter   \
    -I.

LDFLAGS := \
    -T boot/linker.ld       \
    --no-dynamic-linker     \
    -nostdlib

TARGET  := kernel8.img
ELF     := kernel8.elf

OBJS :=             \
    boot/startup.o  \
    drivers/uart.o  \
    kernel/mm.o     \
    kernel/main.o   \
    sd/sd.o         \
    sd/fat32.o      \
    shell/shell.o

# ---- Build rules ---------------------------------------------------

.PHONY: all clean disasm

all: $(TARGET)

$(TARGET): $(ELF)
	$(OBJCOPY) -O binary $< $@
	@printf "  IMAGE  %s  (%d bytes)\n" $@ $$(wc -c < $@)

$(ELF): $(OBJS)
	$(LD) $(LDFLAGS) -o $@ $(OBJS)
	@printf "  LD     %s\n" $@

%.o: %.S
	@printf "  AS     %s\n" $<
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.c
	@printf "  CC     %s\n" $<
	$(CC) $(CFLAGS) -c $< -o $@

disasm: $(ELF)
	$(OBJDUMP) -d $(ELF) | less

clean:
	rm -f $(OBJS) $(ELF) $(TARGET)
	@printf "  CLEAN  done\n"

# Verify the cross-compiler is installed
check-toolchain:
	@which $(CC) >/dev/null 2>&1 || \
		(echo "Install: sudo apt install gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu" && exit 1)
	@printf "  TOOLCHAIN  %s OK\n" $(CC)
