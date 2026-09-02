/* sim_util.c */
#include "sim_util.h"

int sim_strlen(const char *s)
{
    int n = 0;
    while (s && s[n]) n++;
    return n;
}

static char low(char c)
{
    if (c >= 'A' && c <= 'Z') return (char)(c + ('a' - 'A'));
    return c;
}

int sim_strcasecmp(const char *a, const char *b)
{
    while (*a && *b) {
        char ca = low(*a), cb = low(*b);
        if (ca != cb) return (int)(unsigned char)ca - (int)(unsigned char)cb;
        a++; b++;
    }
    return (int)(unsigned char)*a - (int)(unsigned char)*b;
}

int sim_strncasecmp(const char *a, const char *b, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        char ca = low(a[i]), cb = low(b[i]);
        if (ca != cb) return (int)(unsigned char)ca - (int)(unsigned char)cb;
        if (ca == 0) break;
    }
    return 0;
}

int sim_strcmp(const char *a, const char *b)
{
    while (*a && *b && *a == *b) { a++; b++; }
    return (int)(unsigned char)*a - (int)(unsigned char)*b;
}

int sim_memcmp(const void *a, const void *b, int n)
{
    const unsigned char *pa = (const unsigned char *)a;
    const unsigned char *pb = (const unsigned char *)b;
    int i;
    for (i = 0; i < n; i++) {
        if (pa[i] != pb[i]) return (int)pa[i] - (int)pb[i];
    }
    return 0;
}

void sim_memcpy(void *dst, const void *src, int n)
{
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    int i;
    for (i = 0; i < n; i++) d[i] = s[i];
}

int sim_strlcpy(char *dst, const char *src, int n)
{
    int i = 0;
    if (n <= 0) return 0;
    while (src[i] && i < n - 1) { dst[i] = src[i]; i++; }
    dst[i] = '\0';
    return i;
}

int sim_atoi(const char *s)
{
    int v = 0, neg = 0;
    if (s == 0) return 0;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return neg ? -v : v;
}

int sim_hex_to_bytes(const char *hex, uint8_t *out, int max_bytes)
{
    int i, j = 0, hi = -1;
    if (hex == 0) return 0;
    for (i = 0; hex[i]; i++) {
        char c = hex[i];
        int v;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else if (c == ':' || c == '-' || c == ' ') continue;  /* separator */
        else break;
        if (hi < 0) { hi = v; continue; }
        if (j >= max_bytes) return j;
        out[j++] = (uint8_t)((hi << 4) | v);
        hi = -1;
    }
    return j;
}

void sim_bytes_to_hex(const uint8_t *in, int len, char *out)
{
    static const char hex[] = "0123456789abcdef";
    int i;
    for (i = 0; i < len; i++) {
        out[i * 2] = hex[in[i] >> 4];
        out[i * 2 + 1] = hex[in[i] & 0xF];
    }
    out[len * 2] = '\0';
}

char *sim_strlower(char *s)
{
    char *p = s;
    while (*p) { *p = low(*p); p++; }
    return s;
}

int sim_strchr(const char *s, char c)
{
    int i = 0;
    while (s[i]) { if (s[i] == c) return i; i++; }
    return -1;
}

char *sim_token(char *s, char delim)
{
    char *next;
    if (s == 0) return 0;
    next = s;
    while (*next && *next != delim) next++;
    if (*next) { *next = '\0'; next++; } else { next = 0; }
    return next;
}

uint8_t sim_crc8(const uint8_t *data, uint16_t len)
{
    return sim_crc8_update(0, data, len);
}

uint8_t sim_crc8_update(uint8_t crc, const uint8_t *data, uint16_t len)
{
    uint16_t i;
    for (i = 0; i < len; i++) {
        uint8_t b = data[i];
        int k;
        crc ^= b;
        for (k = 0; k < 8; k++) {
            if (crc & 0x80) crc = (uint8_t)((crc << 1) ^ 0x07);
            else crc = (uint8_t)(crc << 1);
        }
    }
    return crc;
}
