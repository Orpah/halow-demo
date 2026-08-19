/* sim_util.h — small self-contained helpers (no libc dependency) */
#ifndef __SIM_UTIL_H__
#define __SIM_UTIL_H__

#include <stdint.h>

/* case-insensitive compare: return 0 if equal */
int sim_strcasecmp(const char *a, const char *b);

/* compare first n bytes, case-insensitive */
int sim_strncasecmp(const char *a, const char *b, int n);

int sim_strlen(const char *s);

/* copy at most n-1 chars, always NUL-terminate; returns copied length */
int sim_strlcpy(char *dst, const char *src, int n);

int sim_strcmp(const char *a, const char *b);

/* byte compare, return 0 if equal */
int sim_memcmp(const void *a, const void *b, int n);

/* byte copy */
void sim_memcpy(void *dst, const void *src, int n);

/* decimal string -> int (stops at non-digit) */
int sim_atoi(const char *s);

/* parse hex string into bytes; returns number of bytes written */
int sim_hex_to_bytes(const char *hex, uint8_t *out, int max_bytes);

/* bytes -> hex lowercase string (needs out >= 2*len+1) */
void sim_bytes_to_hex(const uint8_t *in, int len, char *out);

/* lowercase a string in place, return pointer */
char *sim_strlower(char *s);

/* find first occurrence of c, returns index or -1 */
int sim_strchr(const char *s, char c);

/* split first token by delimiter, NUL-terminate token, return next ptr */
char *sim_token(char *s, char delim);

/* CRC8, poly 0x07, init 0x00 (CRC-8/ATM) */
uint8_t sim_crc8(const uint8_t *data, uint16_t len);
/* continue a CRC8 computation from a running value */
uint8_t sim_crc8_update(uint8_t crc, const uint8_t *data, uint16_t len);

#endif /* __SIM_UTIL_H__ */
