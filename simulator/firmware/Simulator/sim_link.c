/* sim_link.c — UART2 framed link (virtual air) */
#include "sim_link.h"
#include "sim_util.h"
#include "sim_at.h"
#include "board.h"
#include "uart.h"

#define LINK_SYNC1 0xAA
#define LINK_SYNC2 0x55

enum {
    LINK_ST_SYNC1, LINK_ST_SYNC2, LINK_ST_TYPE, LINK_ST_LENH,
    LINK_ST_LENL, LINK_ST_CRC, LINK_ST_PAYLOAD
};

static uint8_t  s_st;
static uint8_t  s_type;
static uint16_t s_len, s_idx;
static uint8_t  s_crc;

static struct {
    uint8_t  ready;
    uint8_t  type;
    uint16_t len;
    uint8_t  data[SIM_LINK_MAX];
} s_rx;

static uint32_t s_tx_pkts, s_rx_pkts;

uint32_t sim_link_tx_pkts(void) { return s_tx_pkts; }
uint32_t sim_link_rx_pkts(void) { return s_rx_pkts; }

/* byte parser, called from USART2 RX ISR context */
static void link_on_byte(uint8_t b)
{
    switch (s_st) {
    case LINK_ST_SYNC1:
        if (b == LINK_SYNC1) s_st = LINK_ST_SYNC2;
        break;
    case LINK_ST_SYNC2:
        s_st = (b == LINK_SYNC2) ? LINK_ST_TYPE : LINK_ST_SYNC1;
        break;
    case LINK_ST_TYPE:
        s_type = b;
        s_crc = b;
        s_st = LINK_ST_LENH;
        break;
    case LINK_ST_LENH:
        s_len = (uint16_t)(b << 8);
        s_crc ^= b;
        s_st = LINK_ST_LENL;
        break;
    case LINK_ST_LENL:
        s_len |= b;
        s_crc ^= b;
        s_idx = 0;
        if (s_len == 0) s_st = LINK_ST_CRC;
        else if (s_len > SIM_LINK_MAX) s_st = LINK_ST_SYNC1; /* oversize: drop */
        else s_st = LINK_ST_PAYLOAD;
        break;
    case LINK_ST_PAYLOAD:
        if (s_idx < s_len) s_rx.data[s_idx++] = b;
        s_crc ^= b;
        if (s_idx >= s_len) s_st = LINK_ST_CRC;
        break;
    case LINK_ST_CRC:
        if (b == s_crc && !s_rx.ready) {
            s_rx.ready = 1;
            s_rx.type = s_type;
            s_rx.len = s_len;
            s_rx_pkts++;
        }
        s_st = LINK_ST_SYNC1;
        break;
    default:
        s_st = LINK_ST_SYNC1;
        break;
    }
}

void sim_link_init(void)
{
    s_st = LINK_ST_SYNC1;
    s_rx.ready = 0;
    s_tx_pkts = s_rx_pkts = 0;
    uart_init(LINK_UART, GPIOA, LINK_TX_PIN, LINK_RX_PIN,
              LINK_BAUD, LINK_UART_IRQn, link_on_byte);
}

void sim_link_send(uint8_t type, const uint8_t *payload, uint16_t len)
{
    uint8_t hdr[6];
    uint8_t crc = type;
    uint16_t i;

    hdr[0] = LINK_SYNC1;
    hdr[1] = LINK_SYNC2;
    hdr[2] = type;
    hdr[3] = (uint8_t)(len >> 8);
    hdr[4] = (uint8_t)(len & 0xFF);
    crc ^= hdr[3];
    crc ^= hdr[4];
    for (i = 0; i < len; i++) crc ^= payload[i];
    hdr[5] = crc;

    uart_write(LINK_UART, hdr, sizeof(hdr));
    if (len) uart_write(LINK_UART, payload, len);
    s_tx_pkts++;
}

void sim_link_poll(void)
{
    uint8_t type;
    uint16_t len;
    uint8_t *data;

    if (!s_rx.ready) return;
    type = s_rx.type;
    len  = s_rx.len;
    data = s_rx.data;
    s_rx.ready = 0;

    /* Frame monitor: when WNB debug is on, dump received DATA frames as hex
     * to the console (main-loop context, safe to print). The UI parses the
     * "FRAME:RX <hex>" lines. TX frames are not printed here to avoid
     * blocking UART in the SPI RX ISR path. */
    if (sim_at_dbg_wnb() && type == SIM_LINK_TYPE_DATA) {
        char hex[2 * SIM_LINK_MAX + 1];
        if (len <= SIM_LINK_MAX) {
            sim_bytes_to_hex(data, (int)len, hex);
            uart_printf(CONSOLE_UART, "FRAME:RX %s\r\n", hex);
        }
    }

    sim_link_handle_frame(type, data, len);
}
