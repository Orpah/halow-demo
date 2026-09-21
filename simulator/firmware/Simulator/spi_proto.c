/* spi_proto.c — SPI 宿主接口协议层（纯逻辑，无寄存器/中断；可编进固件、也可在 host 上跑）。
 * 详见 spi_proto.h 与 docs/spi_protocol.md §2/§3。 */
#include "spi_proto.h"

#include "sim_util.h"        /* sim_crc8 / sim_crc8_update —— 固件里 CRC 的单一源 */

uint8_t spi_proto_crc(uint8_t cmd, const uint8_t *payload, uint16_t len)
{
    uint8_t hdr[3];

    hdr[0] = (uint8_t)(cmd & 0x7F);
    hdr[1] = (uint8_t)(len >> 8);
    hdr[2] = (uint8_t)(len & 0xFF);
    if (payload == NULL || len == 0) {
        return sim_crc8(hdr, 3);
    }
    return sim_crc8_update(sim_crc8(hdr, 3), payload, len);
}

void spi_proto_rx_reset(spi_proto_rx_t *rx)
{
    if (rx == NULL) return;
    rx->hdr_idx = 0;
    rx->cmd = 0;
    rx->len = 0;
    rx->idx = 0;
    rx->done = 0;
}

void spi_proto_cs_start(spi_proto_rx_t *rx)
{
    spi_proto_rx_reset(rx);
}

void spi_proto_cs_end(spi_proto_rx_t *rx)
{
    if (rx == NULL) return;
    rx->done = 1;                    /* 事务结束：此后到下次 CS 拉低前的字节忽略 */
    rx->hdr_idx = 0;
}

/* 与 SPI 中断里被调用的顺序一致：先发应答字节（由调用方做），再喂这里。
 * ⚠ 主机每读走一个应答字节，就必然多发一个 MOSI 字节（全双工），所以响应阶段的
 *   那些字节会落到这里 —— 靠 `done` 忽略掉。 */
spi_rx_ev_t spi_proto_rx_byte(spi_proto_rx_t *rx, uint8_t b)
{
    if (rx == NULL || rx->done) {
        return SPI_RX_IGNORED;
    }
    if (rx->hdr_idx < SPI_PROTO_HDR) {
        rx->hdr[rx->hdr_idx++] = b;
        if (rx->hdr_idx == SPI_PROTO_HDR) {
            rx->cmd = (uint8_t)(rx->hdr[0] & 0x7F);
            rx->len = (uint16_t)(((uint16_t)rx->hdr[1] << 8) | rx->hdr[2]);
            rx->idx = 0;
            if (rx->len > SPI_PROTO_MAX_FRAME) {
                rx->done = 1;
                return SPI_RX_TOO_LONG;
            }
            if (rx->len == 0) {
                rx->done = 1;
                return (spi_proto_crc(rx->cmd, NULL, 0) == rx->hdr[3])
                       ? SPI_RX_FRAME : SPI_RX_BAD_CRC;
            }
        }
        return SPI_RX_NEED_MORE;
    }
    if (rx->idx < rx->len) {
        rx->buf[rx->idx++] = b;
    }
    if (rx->idx >= rx->len) {
        rx->done = 1;
        return (spi_proto_crc(rx->cmd, rx->buf, rx->len) == rx->hdr[3])
               ? SPI_RX_FRAME : SPI_RX_BAD_CRC;
    }
    return SPI_RX_NEED_MORE;
}

uint8_t spi_proto_rx_cmd(const spi_proto_rx_t *rx)
{
    return (rx == NULL) ? 0 : rx->cmd;
}

uint16_t spi_proto_rx_declared_len(const spi_proto_rx_t *rx)
{
    return (rx == NULL) ? 0 : rx->len;
}

const uint8_t *spi_proto_rx_payload(const spi_proto_rx_t *rx, uint16_t *len)
{
    if (rx == NULL || rx->len == 0 || rx->len > SPI_PROTO_MAX_FRAME ||
        rx->idx < rx->len) {
        if (len != NULL) *len = 0;
        return NULL;
    }
    if (len != NULL) *len = rx->len;
    return rx->buf;
}

uint16_t spi_proto_build_resp(uint8_t *out, size_t outcap, uint8_t cmd,
                              const uint8_t *payload, uint16_t len)
{
    uint16_t i;

    if (out == NULL || (size_t)SPI_PROTO_HDR + (size_t)len > outcap) {
        return 0;
    }
    out[0] = (uint8_t)((cmd & 0x7F) | SPI_PROTO_RESP_FLAG);
    out[1] = (uint8_t)(len >> 8);
    out[2] = (uint8_t)(len & 0xFF);
    out[3] = spi_proto_crc(cmd, payload, len);
    for (i = 0; i < len; i++) {                 /* 向前拷：out == payload 也安全 */
        out[SPI_PROTO_HDR + i] = payload[i];
    }
    return (uint16_t)(SPI_PROTO_HDR + len);
}
