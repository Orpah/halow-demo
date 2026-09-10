/*
 * luhn32.c — Luhn mod 32 校验（Crockford Base32）C 参考实现
 *
 * 与 Python 参考实现 ../orpah_id.py 的 compute_check_luhn32 / verify_check_luhn32
 * 完全一致。校验位只算 ORG-UNIQUE（不含 CC；CC=ISO 3166-1 alpha-2 不参与校验）。
 *
 * 用法：
 *   luhn32 compute <ORG-UNIQUE>        计算 1 位校验字符（跳过分隔符 '-'；不含 CC）
 *   luhn32 verify  <ORG-UNIQUE-CHECK>  校验整串（含校验字符；不含 CC），输出 1/0
 *   luhn32 batch                       从 stdin 逐行读 ORG-UNIQUE，输出「ORG-UNIQUE\t校验字符」
 *   luhn32 selftest [vectors.txt]      跑测试向量（默认 test_vectors_luhn32.txt），全过 PASS
 *
 * 编译（任选其一）：
 *   MSVC: cl /nologo /utf-8 luhn32.c
 *   GCC : gcc -std=c99 -O2 -o luhn32 luhn32.c
 * 跨语言一致性由 ../c/run_cross_test.py 一键验证（Python vs C 零偏差）。
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const char *CA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/* Crockford Base32 字符 → 索引（0-31）；非法字符（含 I L O U）返回 0xFF。 */
static uint8_t char_to_index(char c) {
    if (c >= 'a' && c <= 'z') c -= 'a' - 'A';     /* 小写 → 大写 */
    for (uint8_t i = 0; i < 32; i++)
        if (CA[i] == c) return i;
    return 0xFF;
}

static char index_to_char(uint8_t idx) {
    return (idx < 32) ? CA[idx] : '\0';
}

/* 输入 ORG-UNIQUE（可含 '-'）→ 数字序列。返回 1 成功（*n=长度），0 非法字符。 */
static int to_digits(const char *input, uint8_t *out, size_t *n) {
    *n = 0;
    for (const char *p = input; *p; p++) {
        if (*p == '-') continue;                  /* 跳过分隔符 */
        uint8_t idx = char_to_index(*p);
        if (idx == 0xFF) return 0;
        out[(*n)++] = idx;
    }
    return 1;
}

/* Luhn 校验和：从右往左隔位翻倍，模 32 */
static int luhn_sum(const uint8_t *d, size_t n) {
    int s = 0, dbl = 0;
    for (size_t i = n; i-- > 0; ) {
        if (dbl) { int d2 = d[i] * 2; s += d2 / 32 + d2 % 32; }
        else s += d[i];
        dbl = !dbl;
    }
    return s;
}

/* 计算 Luhn32 校验字符（输入 = ORG-UNIQUE，不含 CC）。非法输入返回 '\0'。 */
char luhn32_compute(const char *input) {
    uint8_t d[256];
    size_t n;
    if (!to_digits(input, d, &n)) return '\0';
    for (uint8_t c = 0; c < 32; c++) {
        d[n] = c;
        if (luhn_sum(d, n + 1) % 32 == 0) return index_to_char(c);
    }
    return '0';   /* 理论不可达 */
}

/* 验证（输入 = ORG-UNIQUE-CHECK，不含 CC）。 */
int luhn32_verify(const char *input) {
    uint8_t d[256];
    size_t n;
    if (!to_digits(input, d, &n)) return 0;
    return luhn_sum(d, n) % 32 == 0;
}

/* ---- 测试向量（test_vectors_luhn32.txt：每行「ORG-UNIQUE<TAB>校验字符」）---- */
static int selftest(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return 2; }
    char line[256];
    int n = 0, fail = 0;
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '\0' || *p == '\r' || *p == '\n' || *p == '#') continue;
        char *nl = strpbrk(p, "\r\n");
        if (nl) *nl = '\0';
        char *tab = strchr(p, '\t');
        if (!tab || tab[1] == '\0') continue;
        *tab = '\0';
        char c = luhn32_compute(p);
        char full[256];
        snprintf(full, sizeof(full), "%s-%c", p, c);
        int v = luhn32_verify(full);
        if (c != tab[1] || v != 1) {
            fail++;
            printf("FAIL  core=%-24s compute=%c expect=%c verify=%d\n", p, c, tab[1], v);
        }
        n++;
    }
    fclose(f);
    printf("%s: %d/%d vectors passed\n", fail ? "FAIL" : "PASS", n - fail, n);
    return fail ? 1 : 0;
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "selftest") == 0) {
        const char *path = (argc >= 3) ? argv[2] : "test_vectors_luhn32.txt";
        return selftest(path);
    }
    if (argc >= 3 && strcmp(argv[1], "compute") == 0) {
        char c = luhn32_compute(argv[2]);
        if (c == '\0') { printf("INVALID\n"); return 1; }
        printf("%c\n", c);
        return 0;
    }
    if (argc >= 3 && strcmp(argv[1], "verify") == 0) {
        printf("%d\n", luhn32_verify(argv[2]));
        return 0;
    }
    if (argc >= 2 && strcmp(argv[1], "batch") == 0) {
        char line[256];
        while (fgets(line, sizeof(line), stdin)) {
            char *nl = strpbrk(line, "\r\n");
            if (nl) *nl = '\0';
            if (line[0] == '\0') continue;
            char c = luhn32_compute(line);
            printf("%s\t%c\n", line, c == '\0' ? '?' : c);
        }
        return 0;
    }
    fprintf(stderr, "usage: luhn32 compute <ORG-UNIQUE> | verify <ORG-UNIQUE-CHECK> | batch | selftest [vectors.txt]\n");
    return 2;
}
