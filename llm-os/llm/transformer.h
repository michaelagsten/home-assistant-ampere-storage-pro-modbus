#pragma once

#include <stdint.h>
#include <stddef.h>
#include "gguf.h"
#include "tokenizer.h"

/*
 * Transformer inference engine — interface.
 *
 * Implements autoregressive next-token prediction using the LLaMA-style
 * decoder-only transformer architecture (compatible with LLaMA 2/3,
 * Mistral, Phi-2, TinyLlama, and other GGUF-distributed models).
 *
 * Key operations per forward pass:
 *   1. Token embedding lookup
 *   2. For each layer:
 *      a. RMS-LayerNorm
 *      b. Grouped-Query Attention (GQA) with RoPE positional encoding
 *      c. KV-cache update (avoids recomputing past keys/values)
 *      d. Feed-forward network (SwiGLU activation)
 *   3. Final RMS-LayerNorm + logit projection
 *   4. Greedy / temperature sampling of next token
 *
 * Memory requirements (example: TinyLlama 1.1B Q4_0 on RPi5 8 GB):
 *   Weights:   ~637 MB (4-bit quantised, loaded from SD card)
 *   KV-cache:  n_layer × n_ctx × n_head_kv × head_dim × 2 × sizeof(float)
 *              = 22 × 2048 × 4 × 64 × 2 × 4 ≈ 90 MB
 *   Activations: ~few MB (reused each step)
 */

/* Temperature = 0.0 → greedy (always pick the highest-probability token) */
#define TEMPERATURE_GREEDY 0.0f
#define TEMPERATURE_DEFAULT 0.8f

typedef struct {
    const gguf_model_t  *model;
    const tokenizer_t   *tokenizer;

    /* KV-cache: [layer][position][head][dim] stored as float */
    float   *k_cache;   /* shape: n_layer × n_ctx × n_head_kv × head_dim */
    float   *v_cache;   /* same shape                                     */

    /* Scratch buffers reused each forward pass (allocated once at init) */
    float   *x;         /* current activation vector [n_embd]             */
    float   *xb;        /* scratch [n_embd]                               */
    float   *q;         /* query  [n_head × head_dim]                     */
    float   *k;         /* key    [n_head_kv × head_dim]                  */
    float   *v;         /* value  [n_head_kv × head_dim]                  */
    float   *att;       /* attention scores [n_head × n_ctx]              */
    float   *logits;    /* output logits [n_vocab]                        */

    uint32_t pos;       /* current position in context (tokens generated) */
} transformer_t;

/*
 * Allocate KV-cache and scratch buffers from the mm heap.
 * Must be called before transformer_generate().
 *
 * Returns 0 on success, -1 on OOM.
 */
int transformer_init(transformer_t *t,
                     const gguf_model_t *model,
                     const tokenizer_t  *tokenizer);

/*
 * Run one full forward pass and return the next token ID.
 *
 * token  — the current input token (or BOS for the first call)
 * pos    — position in the sequence (0-based)
 * temp   — sampling temperature (0.0 = greedy)
 *
 * Returns the sampled next token ID.
 */
uint32_t transformer_forward(transformer_t *t, uint32_t token,
                             uint32_t pos, float temp);

/*
 * High-level: generate up to max_new_tokens tokens from a prompt string.
 *
 * The callback is called once per generated token with the decoded string
 * fragment, enabling streaming output to the UART without buffering the
 * entire response.
 *
 * Returns total number of tokens generated.
 */
typedef void (*token_callback_t)(const char *text, void *user_data);

int transformer_generate(transformer_t   *t,
                         const char      *prompt,
                         size_t           max_new_tokens,
                         float            temperature,
                         token_callback_t on_token,
                         void            *user_data);

/* Reset the KV-cache (start a new conversation) */
void transformer_reset(transformer_t *t);
