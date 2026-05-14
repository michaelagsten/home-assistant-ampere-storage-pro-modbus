#pragma once

#include <stdint.h>
#include <stddef.h>

/*
 * GGUF model format — header and loader interface.
 *
 * GGUF (GGML Universal Format) is the standard on-disk format used by
 * llama.cpp and compatible tools.  It is well-documented, has a stable
 * magic number, and stores all metadata inline so we can parse it with
 * no external schema.
 *
 * Format overview (version 3):
 *   [magic u32] [version u32] [tensor_count u64] [kv_count u64]
 *   [kv_pairs …]        ← model hyperparameters, tokenizer vocab, etc.
 *   [tensor_infos …]    ← name, shape, dtype, data offset for each tensor
 *   [alignment padding]
 *   [tensor data …]     ← raw weight bytes
 *
 * We parse just enough to fill gguf_model_t; full tensor access is done
 * via direct pointer arithmetic into the mmap'd / SD-loaded weight buffer.
 */

#define GGUF_MAGIC   0x46554747u    /* "GGUF" little-endian */
#define GGUF_VERSION 3u

/* ------------------------------------------------------------------ */
/* Value types for key-value metadata entries                          */
/* ------------------------------------------------------------------ */
typedef enum {
    GGUF_TYPE_UINT8   = 0,
    GGUF_TYPE_INT8    = 1,
    GGUF_TYPE_UINT16  = 2,
    GGUF_TYPE_INT16   = 3,
    GGUF_TYPE_UINT32  = 4,
    GGUF_TYPE_INT32   = 5,
    GGUF_TYPE_FLOAT32 = 6,
    GGUF_TYPE_BOOL    = 7,
    GGUF_TYPE_STRING  = 8,
    GGUF_TYPE_ARRAY   = 9,
    GGUF_TYPE_UINT64  = 10,
    GGUF_TYPE_INT64   = 11,
    GGUF_TYPE_FLOAT64 = 12,
} gguf_type_t;

/* Quantisation types we care about for inference */
typedef enum {
    GGML_TYPE_F32  = 0,
    GGML_TYPE_F16  = 1,
    GGML_TYPE_Q4_0 = 2,
    GGML_TYPE_Q4_1 = 3,
    GGML_TYPE_Q8_0 = 8,
    GGML_TYPE_Q5_0 = 6,
    GGML_TYPE_Q5_1 = 7,
} ggml_type_t;

/* ------------------------------------------------------------------ */
/* Parsed model descriptor                                             */
/* ------------------------------------------------------------------ */
typedef struct {
    /* Pointers into the raw weight buffer loaded from SD card */
    const void  *raw;           /* start of entire GGUF file in RAM     */
    size_t       raw_size;      /* total bytes                           */
    const void  *vocab_data;    /* pointer to tokenizer data in raw buf  */
    size_t       vocab_data_size;

    /* Hyperparameters extracted from GGUF metadata */
    uint32_t n_vocab;           /* vocabulary size                       */
    uint32_t n_ctx;             /* maximum context length                */
    uint32_t n_embd;            /* embedding / hidden dimension          */
    uint32_t n_head;            /* number of attention heads             */
    uint32_t n_head_kv;         /* number of KV heads (GQA)             */
    uint32_t n_layer;           /* transformer depth                     */
    uint32_t n_ff;              /* feed-forward hidden size              */
    float    rope_freq_base;    /* RoPE base frequency (default 10000)   */

    /* Architecture string, e.g. "llama", "mistral", "phi2" */
    char arch[32];
} gguf_model_t;

/* ------------------------------------------------------------------ */
/* API                                                                 */
/* ------------------------------------------------------------------ */

/*
 * Parse a GGUF file already loaded into memory.
 *
 * data     — pointer to the raw bytes of the .gguf file
 * len      — total byte count
 * out      — filled on success
 *
 * Returns 0 on success, negative error code on failure.
 */
int gguf_load(const void *data, size_t len, gguf_model_t *out);

/*
 * Look up a tensor by name.  Returns a pointer to its weight data
 * within the raw buffer, or NULL if not found.
 */
const void *gguf_tensor_data(const gguf_model_t *m, const char *name,
                             ggml_type_t *type_out, size_t *size_out);
