/* spi_proto_cli.c — **主机侧**命令行：把设备侧的协议层（firmware/Simulator/spi_proto.c）
 * 拿到 PC 上跑，用来和 Python 主机模型（tools/spi_frame.py）逐字节对拍。
 *
 * ★ **不编进固件**（固件的 Makefile 里没有它；它只服务于 tools/check_spi_proto.py）。
 *   "不编进固件"这件事本身是检查项：设备侧协议层必须**不碰任何寄存器**，
 *   否则它就没法在 PC 上跑，也就失去这层拆分的大部分价值。
 *
 * 用法：
 *   spi_proto_cli crc  <cmd-hex> <payload-hex>       → 校验字节
 *   spi_proto_cli req  <cmd-hex> <payload-hex>       → 请求帧（hex）
 *   spi_proto_cli resp <cmd-hex> <payload-hex>       → 应答帧（hex）
 *   spi_proto_cli rx   <stream-hex>[|<stream-hex>]…  → 逐字节喂接收状态机
 *        `|` = NSS 上升沿（事务结束）；每个 `|` 分段各自是一次 CS 事务。
 *        每收完一帧打一行：`<ev> <cmd> <len> <payload-hex>`
 *        （ev ∈ frame / bad_crc / too_long；cmd/len 是十进制）
 *
 * 约定：`<payload-hex>` 允许为空串（argv 里写成 ""）。输出一律小写 hex，便于逐字比对。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sim_util.h"
#include "spi_proto.h"

#define MAXP SPI_PROTO_MAX_FRAME

static void print_hex(const uint8_t *b, int n)
{
    char buf[MAXP * 2 + 1];
    sim_bytes_to_hex(b, n, buf);
    fputs(buf, stdout);
}

static int arg_bytes(const char *hex, uint8_t *out)
{
    if (hex == NULL || hex[0] == '\0' || (hex[0] == '-' && hex[1] == '\0')) {
        return 0;                        /* `-`（或空串）= 空载荷 */
    }
    return sim_hex_to_bytes(hex, out, MAXP);
}

int main(int argc, char **argv)
{
    static uint8_t pl[MAXP];
    static uint8_t out[SPI_PROTO_HDR + MAXP];
    const char *sub;
    uint8_t cmd;

    if (argc < 3) {
        fprintf(stderr, "usage: spi_proto_cli crc|req|resp <cmd-hex> <payload-hex>\n"
                        "       spi_proto_cli rx <stream-hex>[|<stream-hex>]...\n");
        return 2;
    }
    sub = argv[1];

    if (strcmp(sub, "rx") == 0) {
        static spi_proto_rx_t rx;
        const char *seg = argv[2];

        while (seg != NULL && *seg != '\0') {
            const char *bar = strchr(seg, '|');
            size_t seglen = (bar != NULL) ? (size_t)(bar - seg) : strlen(seg);
            char tmp[2 * MAXP + 2];
            int n, i;

            if (seglen >= sizeof(tmp)) seglen = sizeof(tmp) - 1;
            memcpy(tmp, seg, seglen);
            tmp[seglen] = '\0';

            spi_proto_cs_start(&rx);                 /* NSS 下降沿 */
            n = arg_bytes(tmp, pl);
            for (i = 0; i < n; i++) {
                spi_rx_ev_t ev = spi_proto_rx_byte(&rx, pl[i]);
                if (ev == SPI_RX_FRAME || ev == SPI_RX_BAD_CRC || ev == SPI_RX_TOO_LONG) {
                    const char *name = (ev == SPI_RX_FRAME) ? "frame"
                                     : (ev == SPI_RX_BAD_CRC) ? "bad_crc" : "too_long";
                    uint16_t plen = 0;
                    const uint8_t *pp = spi_proto_rx_payload(&rx, &plen);
                    /* 打印格式与 Python 模型一致：`<ev> <cmd> <len>[ <payload-hex>]`；
                     * too_long 时载荷根本不存在 ⇒ 打**声明的** LEN（那个才是现场要紧的数）。*/
                    printf("%s %u %u", name, (unsigned)spi_proto_rx_cmd(&rx),
                           (unsigned)((ev == SPI_RX_TOO_LONG)
                                      ? spi_proto_rx_declared_len(&rx) : plen));
                    if (pp != NULL && plen > 0) {
                        fputc(' ', stdout);
                        print_hex(pp, (int)plen);
                    }
                    fputc('\n', stdout);
                }
            }
            spi_proto_cs_end(&rx);                   /* NSS 上升沿 */

            seg = (bar != NULL) ? bar + 1 : NULL;
        }
        return 0;
    }

    cmd = (uint8_t)strtol(argv[2], NULL, 16);
    {
        int n = (argc > 3) ? arg_bytes(argv[3], pl) : 0;

        if (strcmp(sub, "crc") == 0) {
            printf("%02x\n", (unsigned)spi_proto_crc(cmd, n ? pl : NULL, (uint16_t)n));
        } else if (strcmp(sub, "req") == 0) {
            out[0] = cmd;
            out[1] = (uint8_t)((uint16_t)n >> 8);
            out[2] = (uint8_t)((uint16_t)n & 0xFF);
            out[3] = spi_proto_crc(cmd, n ? pl : NULL, (uint16_t)n);
            if (n > 0) memcpy(out + SPI_PROTO_HDR, pl, (size_t)n);
            print_hex(out, SPI_PROTO_HDR + n);
            fputc('\n', stdout);
        } else if (strcmp(sub, "resp") == 0) {
            uint16_t total = spi_proto_build_resp(out, sizeof(out), cmd, n ? pl : NULL, (uint16_t)n);
            if (total == 0) { fprintf(stderr, "build failed\n"); return 1; }
            print_hex(out, (int)total);
            fputc('\n', stdout);
        } else if (strcmp(sub, "respip") == 0) {
            /* **就地**构造：载荷已经落在 out+4（设备侧 DATA_RX 就是这样：载荷先落在 tx 缓冲里，
             * 随后就地把 4 字节头补上）。这条路径最容易写错（重叠搬），单独拿出来比。 */
            uint16_t total;
            if (n > 0) memcpy(out + SPI_PROTO_HDR, pl, (size_t)n);
            total = spi_proto_build_resp(out, sizeof(out), cmd, out + SPI_PROTO_HDR, (uint16_t)n);
            if (total == 0) { fprintf(stderr, "build failed\n"); return 1; }
            print_hex(out, (int)total);
            fputc('\n', stdout);
        } else {
            fprintf(stderr, "unknown subcommand: %s\n", sub);
            return 2;
        }
    }
    return 0;
}
