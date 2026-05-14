#pragma once

#include "../llm/transformer.h"

/*
 * Natural language shell — the top-level user interface.
 *
 * The shell reads UTF-8 text from UART, submits it to the transformer,
 * and streams the response back token-by-token.  When the transformer is
 * not available it falls back to echo mode so the UART I/O path can be
 * tested independently.
 *
 * Built-in commands (prefix with '/'):
 *   /reset      — clear KV-cache, start a new conversation
 *   /temp <f>   — set sampling temperature (0.0 = greedy)
 *   /tokens <n> — set max new tokens per response
 *   /info       — print model and memory statistics
 *   /halt       — power off / halt the CPU
 */

void shell_run(transformer_t *t);   /* pass NULL for echo-only mode */
