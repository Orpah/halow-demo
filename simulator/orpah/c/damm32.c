/*
 * damm32.c — Damm32 校验（Crockford Base32 的 Damm 算法）C 参考实现
 *
 * 与 Python 参考实现 ../damm32.py 完全一致：
 *   拟群 T[x][y] = 2 · (x ⊕ y)，在 GF(2^5) 上，不可约多项式 p(t) = t^5 + t + 1（系数 0x23）。
 * 该拟群是弱全反对称拟群，满足 Damm 检出「所有单字符替换 + 所有相邻换位」的充要条件。
 *
 * 用法：
 *   damm32 compute <CC-ORG-UNIQUE>      计算 1 位校验字符（跳过分隔符 '-'）
 *   damm32 verify  <SN>                 校验整串（含校验字符），输出 1/0
 *   damm32 batch                        从 stdin 逐行读核心，输出「核心\t校验字符」
 *   damm32 selftest [vectors.txt]       跑测试向量（默认 test_vectors.txt），全过 PASS
 *
 * 编译（任选其一）：
 *   MSVC: cl /nologo /utf-8 damm32.c
 *   GCC : gcc -std=c99 -O2 -o damm32 damm32.c
 * 跨语言一致性由 ../c/run_cross_test.py 一键验证（Python vs C 零偏差）。
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ---- Damm32 拟群：x ⊙ y = 2 · (x ⊕ y)，在 GF(2^5) 上 ---- */
/* 不可约多项式 p(t) = t^5 + t + 1（系数 0x23）。 */

static uint8_t gf_mul(uint8_t a, uint8_t b) {
    uint8_t r = 0;
    for (int i = 0; i < 5; i++) {
        if (b & 1) r ^= a;
        b >>= 1;
        a <<= 1;
        if (a & 0x20) a ^= 0x23;    /* p(t) = t^5 + t + 1 */
    }
    return r & 0x1F;
}

/* 拟群运算：x ⊙ y = 2 · (x ⊕ y)；2 = 域元素 t */
static uint8_t quasigroup(uint8_t x, uint8_t y) {
    return gf_mul(2, x ^ y);
}

/* Crockford Base32 字符 → 索引（0-31）；非法字符（含 I L O U）返回 0xFF。 */
static uint8_t char_to_index(char c) {
    static const char *CA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    if (c >= 'a' && c <= 'z') c -= 'a' - 'A';     /* 小写 → 大写 */
    for (uint8_t i = 0; i < 32; i++)
        if (CA[i] == c) return i;
    return 0xFF;
}

/* 索引 → Crockford Base32 字符（0-31） */
static char index_to_char(uint8_t idx) {
    static const char *CA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    return (idx < 32) ? CA[idx] : '\0';
}

/* 计算 Damm32 校验字符（输入 = CC-ORG-UNIQUE，可含 '-' 分隔符）。非法输入返回 '\0'。 */
char damm32_compute(const char *input) {
    uint8_t interim = 0;
    size_t len = strlen(input);
    for (size_t i = 0; i < len; i++) {
        if (input[i] == '-') continue;            /* 跳过分隔符（与 sn_digits 一致） */
        uint8_t idx = char_to_index(input[i]);
        if (idx == 0xFF) return '\0';
        interim = quasigroup(interim, idx);
    }
    /* 校验位 c 满足 quasigroup(interim, c) == 0；本构造下
     * 2·(interim⊕c) = 0 ⟺ interim⊕c = 0（2 可逆）⟺ c = interim */
    return index_to_char(interim);
}

/* 验证 Damm32 校验（输入包含校验字符）。 */
int damm32_verify(const char *input) {
    uint8_t interim = 0;
    size_t len = strlen(input);
    for (size_t i = 0; i < len; i++) {
        if (input[i] == '-') continue;            /* 跳过分隔符 */
        uint8_t idx = char_to_index(input[i]);
        if (idx == 0xFF) return 0;
        interim = quasigroup(interim, idx);
    }
    return (interim == 0);
}

/* ---- 测试向量（test_vectors.txt：每行「核心<TAB>校验字符」）---- */
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
        char c = damm32_compute(p);
        char full[256];
        snprintf(full, sizeof(full), "%s-%c", p, c);
        int v = damm32_verify(full);
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
        const char *path = (argc >= 3) ? argv[2] : "test_vectors.txt";
        return selftest(path);
    }
    if (argc >= 3 && strcmp(argv[1], "compute") == 0) {
        char c = damm32_compute(argv[2]);
        if (c == '\0') { printf("INVALID\n"); return 1; }
        printf("%c\n", c);
        return 0;
    }
    if (argc >= 3 && strcmp(argv[1], "verify") == 0) {
        printf("%d\n", damm32_verify(argv[2]));
        return 0;
    }
    if (argc >= 2 && strcmp(argv[1], "batch") == 0) {
        char line[256];
        while (fgets(line, sizeof(line), stdin)) {
            char *nl = strpbrk(line, "\r\n");
            if (nl) *nl = '\0';
            if (line[0] == '\0') continue;
            char c = damm32_compute(line);
            printf("%s\t%c\n", line, c == '\0' ? '?' : c);
        }
        return 0;
    }
    fprintf(stderr, "usage: damm32 compute <CC-ORG-UNIQUE> | verify <SN> | batch | selftest [vectors.txt]\n");
    return 2;
}
