#pragma once

#include <stddef.h>
#include <stdint.h>

/*
 * Bump allocator — phase 1 memory manager.
 *
 * Allocates from a linear arena; individual frees are no-ops.
 * This is sufficient for boot-time allocations (tokenizer vocab tables,
 * KV-cache, runtime state) that live for the duration of the session.
 *
 * A proper slab/pool allocator can replace this later without changing
 * the API.
 */

void   mm_init(void *heap_start, size_t heap_size);
void  *mm_alloc(size_t size);           /* 16-byte aligned; returns NULL on OOM */
void   mm_free(void *ptr);              /* no-op in bump allocator */
size_t mm_available(void);             /* remaining bytes */
size_t mm_used(void);                  /* bytes allocated so far */
