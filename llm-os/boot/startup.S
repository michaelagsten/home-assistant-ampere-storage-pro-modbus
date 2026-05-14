/*
 * startup.S — AArch64 bare-metal boot entry for Raspberry Pi 5
 *
 * The GPU firmware loads kernel8.img at physical address 0x80000 and jumps
 * here in AArch64 EL2 (hypervisor level). We:
 *   1. Park cores 1-3 immediately (only core 0 proceeds)
 *   2. Drop from EL2 → EL1 via eret
 *   3. Set up the initial stack pointer
 *   4. Zero the BSS segment
 *   5. Call kernel_main() in C
 */

.section ".text.boot"
.global _start

_start:
    /* ------------------------------------------------------------------ */
    /* Step 1: Park secondary cores.                                       */
    /* MPIDR_EL1 bits [1:0] = CPU id within cluster.                      */
    /* ------------------------------------------------------------------ */
    mrs     x0, mpidr_el1
    and     x0, x0, #0xFF
    cbnz    x0, .Lhalt          // cores 1,2,3 → halt forever

    /* ------------------------------------------------------------------ */
    /* Step 2: Drop to EL1 if we are currently in EL2.                    */
    /* RPi5 firmware starts the ARM cores at EL2.                         */
    /* ------------------------------------------------------------------ */
    mrs     x0, CurrentEL
    lsr     x0, x0, #2          // CurrentEL bits [3:2] → shift to [1:0]
    cmp     x0, #2
    bne     .Lsetup_el1         // already EL1 (shouldn't happen, but safe)

    /* HCR_EL2: set RW=1 so EL1 runs in AArch64 mode */
    mov     x0, #(1 << 31)
    msr     hcr_el2, x0

    /* SCTLR_EL1: write a safe architectural reset value (MMU off, caches off) */
    msr     sctlr_el1, xzr

    /* Return address: jump to EL1 setup code after eret */
    adr     x0, .Lsetup_el1
    msr     elr_el2, x0

    /* SPSR_EL2: EL1h mode + all exception masks set (D,A,I,F) */
    mov     x0, #0x3C5          // 0b11_11_00_0_101 = DAIF | EL1h
    msr     spsr_el2, x0

    eret                        // → .Lsetup_el1 at EL1

    /* ------------------------------------------------------------------ */
    /* Step 3: EL1 — set stack, clear BSS, call C.                        */
    /* ------------------------------------------------------------------ */
.Lsetup_el1:
    /* Stack grows downward from _stack_top (defined in linker.ld) */
    ldr     x0, =_stack_top
    mov     sp, x0

    /* Zero the BSS section (16-byte aligned, see linker.ld) */
    ldr     x0, =__bss_start
    ldr     x1, =__bss_end
.Lbss_loop:
    cmp     x0, x1
    bge     .Lbss_done
    stp     xzr, xzr, [x0], #16
    b       .Lbss_loop
.Lbss_done:

    /* Call C kernel entry — should never return */
    bl      kernel_main

.Lhalt:
    wfe
    b       .Lhalt
