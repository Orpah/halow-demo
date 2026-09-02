/* sim_at.h — AT command engine (TXW8301-compatible subset) */
#ifndef __SIM_AT_H__
#define __SIM_AT_H__

#include <stdint.h>

/* Run one AT line (without trailing CR/LF). If resp != NULL, the textual
 * response is captured there (NUL-terminated) instead of console-only.
 * Returns 0 on success. */
int sim_at_run(const char *line, char *resp, int resp_size);

/* Data-mode (AT+TXDATA): begin collecting 'len' raw bytes */
void sim_at_begin_txdata(uint16_t len);

/* Feed a raw byte while in data-mode; returns 1 if a frame was submitted */
int sim_at_data_byte(uint8_t b);

int sim_at_txdata_active(void);

/* debug print flags (AT+SYSDBG) */
int sim_at_dbg_lmac(void);
int sim_at_dbg_wnb(void);

#endif /* __SIM_AT_H__ */
