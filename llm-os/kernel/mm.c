#include "mm.h"

static uint8_t *arena_ptr;
static uint8_t *arena_end;
static uint8_t *arena_start;

void mm_init(void *start, size_t size)
{
    arena_start = (uint8_t *)start;
    arena_ptr   = arena_start;
    arena_end   = arena_start + size;
}

void *mm_alloc(size_t size)
{
    /* Round up to 16-byte boundary for alignment-sensitive types (float, double) */
    size = (size + 15u) & ~15u;

    if (arena_ptr + size > arena_end)
        return (void *)0;   /* OOM */

    void *ptr  = arena_ptr;
    arena_ptr += size;
    return ptr;
}

void mm_free(void *ptr)
{
    (void)ptr;  /* bump allocator: individual frees are unsupported */
}

size_t mm_available(void)
{
    return (size_t)(arena_end - arena_ptr);
}

size_t mm_used(void)
{
    return (size_t)(arena_ptr - arena_start);
}
