/*
 * mod97.c — Mod 97 校验（IBAN 思路）C 参考实现
 *
 * 与 Python 参考实现 ../orpah_id.py 的 compute_check_mod97 / verify_check_mod97 一致。
 * 校验位只算 ORG-UNIQUE（不含 CC；CC=ISO 3166-1 alpha-2 不参与校验）。
 * 字母 A=10..Z=35、数字 0-9；输出 2 位十进制（02–98，不可能 00/01）。
 *
 * 用法：
 *   mod97 compute <ORG-UNIQUE>        计算 2 位校验码（不含 CC）
 *   mod97 verify  <ORG-UNIQUE-CHECK>  校验整串（含校验码；不含 CC），输出 1/0
 *   mod97 batch                       从 stdin 逐行读 ORG-UNIQUE，输出「ORG-UNIQUE\t校验码」
 *   mod97 selftest [vectors.txt]      跑测试向量（默认 test_vectors_mod97.txt），全过 PASS
 *
 * 编译（任选其一）：
 *   MSVC: cl /nologo /utf-8 mod97.c
 *   GCC : gcc -std=c99 -O2 -o mod97 mod97.c
 * 跨语言一致性由 ../c/run_cross_test.py 一键验证（Python vs C 零偏差）。
 */
#include <stdio.h>
#include <string.h>

/* 对字母数字串（跳过 '-'）取模 97：字母 A=10..Z=35（小写按大写处理），数字 0-9。
 * 非法字符返回 -1。 */
static int mod97(const char *s) {
    int r = 0;
    for (const char *p = s; *p; p++) {
        char c = *p;
        if (c == '-') continue;
        if (c >= '0' && c <= '9') r = (r * 10 + (c - '0')) % 97;
        else if (c >= 'A' && c <= 'Z') r = (r * 100 + (c - 'A' + 10)) % 97;
        else if (c >= 'a' && c <= 'z') r = (r * 100 + (c - 'a' + 10)) % 97;
        else return -1;
    }
    return r;
}

/* 计算 Mod97 校验码（输入 = ORG-UNIQUE，不含 CC）→ 2 位十进制写入 out[3]。
 * 非法输入返回 0（out 未定义）。 */
int mod97_compute(const char *input, char out[3]) {
    char buf[512];
    snprintf(buf, sizeof(buf), "%s00", input);
    int r = mod97(buf);
    if (r < 0) return 0;
    snprintf(out, 3, "%02d", 98 - r);
    return 1;
}

/* 验证（输入 = ORG-UNIQUE-CHECK，不含 CC）。 */
int mod97_verify(const char *input) {
    return mod97(input) == 1;
}

/* ---- 测试向量（test_vectors_mod97.txt：每行「ORG-UNIQUE<TAB>两位校验码」）---- */
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
        char got[3];
        if (!mod97_compute(p, got)) {
            fail++;
            printf("FAIL  core=%-24s compute=INVALID\n", p);
            n++;
            continue;
        }
        char full[256];
        snprintf(full, sizeof(full), "%s-%s", p, got);
        int v = mod97_verify(full);
        if (strcmp(got, tab + 1) != 0 || v != 1) {
            fail++;
            printf("FAIL  core=%-24s compute=%s expect=%s verify=%d\n", p, got, tab + 1, v);
        }
        n++;
    }
    fclose(f);
    printf("%s: %d/%d vectors passed\n", fail ? "FAIL" : "PASS", n - fail, n);
    return fail ? 1 : 0;
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "selftest") == 0) {
        const char *path = (argc >= 3) ? argv[2] : "test_vectors_mod97.txt";
        return selftest(path);
    }
    if (argc >= 3 && strcmp(argv[1], "compute") == 0) {
        char out[3];
        if (!mod97_compute(argv[2], out)) { printf("INVALID\n"); return 1; }
        printf("%s\n", out);
        return 0;
    }
    if (argc >= 3 && strcmp(argv[1], "verify") == 0) {
        printf("%d\n", mod97_verify(argv[2]));
        return 0;
    }
    if (argc >= 2 && strcmp(argv[1], "batch") == 0) {
        char line[256];
        while (fgets(line, sizeof(line), stdin)) {
            char *nl = strpbrk(line, "\r\n");
            if (nl) *nl = '\0';
            if (line[0] == '\0') continue;
            char out[3];
            if (mod97_compute(line, out)) printf("%s\t%s\n", line, out);
            else printf("%s\t?\n", line);
        }
        return 0;
    }
    fprintf(stderr, "usage: mod97 compute <ORG-UNIQUE> | verify <ORG-UNIQUE-CHECK> | batch | selftest [vectors.txt]\n");
    return 2;
}
