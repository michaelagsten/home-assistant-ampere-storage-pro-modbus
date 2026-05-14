#pragma once

#include <stdint.h>
#include <stddef.h>

/*
 * BPE (Byte-Pair Encoding) tokenizer — interface.
 *
 * Compatible with SentencePiece / llama-style vocabularies stored in the
 * GGUF metadata block.  Encode converts UTF-8 text into a token ID
 * sequence; decode reverses that into a UTF-8 string.
 *
 * Implementation notes for bare-metal:
 *   - No heap allocations during encode/decode hot path.
 *   - Vocab table is a flat array of (string pointer, score) pairs sorted
 *     by score for BPE merge lookups.
 *   - String storage comes from mm_alloc() at tokenizer_init() time.
 */

#define TOKENIZER_BOS_ID  1u    /* beginning-of-sequence token */
#define TOKENIZER_EOS_ID  2u    /* end-of-sequence token       */

typedef struct {
    const char  *text;      /* token string (points into mm heap) */
    float        score;     /* BPE merge score                    */
    uint32_t     id;        /* token id                           */
} token_entry_t;

typedef struct {
    token_entry_t *entries;     /* sorted vocab table   */
    uint32_t       vocab_size;
    uint32_t       max_token_len;
} tokenizer_t;

/*
 * Initialise tokenizer from the vocab section inside a GGUF file.
 *
 * vocab_data      — pointer to raw GGUF vocab metadata block
 * vocab_data_size — byte length of that block
 *
 * Returns 0 on success.
 */
int tokenizer_init(tokenizer_t *t, const void *vocab_data, size_t vocab_data_size);

/*
 * Encode UTF-8 text into token IDs.
 *
 * text       — null-terminated input string
 * out        — caller-supplied buffer for token IDs
 * max_tokens — capacity of out[]
 * add_bos    — prepend BOS token when non-zero
 *
 * Returns number of tokens written, or -1 on overflow.
 */
int tokenizer_encode(const tokenizer_t *t, const char *text,
                     uint32_t *out, size_t max_tokens, int add_bos);

/*
 * Decode token IDs into a UTF-8 string.
 *
 * tokens  — input token ID array
 * n       — number of tokens
 * out     — caller-supplied output buffer
 * out_len — capacity of out[]
 *
 * Returns number of bytes written (excluding null terminator).
 */
int tokenizer_decode(const tokenizer_t *t,
                     const uint32_t *tokens, size_t n,
                     char *out, size_t out_len);

/* Decode a single token — useful for streaming output one token at a time */
const char *tokenizer_id_to_str(const tokenizer_t *t, uint32_t id);
