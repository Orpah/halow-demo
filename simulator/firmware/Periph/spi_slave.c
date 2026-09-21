/* spi_slave.c — SPI1 slave, framed host interface
 *
 * Frame : [CMD][LEN_H][LEN_L][CRC8][PAYLOAD...]
 *   host -> sim : request   (4+LEN bytes)
 *   sim -> host : response, shifted out in the SAME CS transaction
 *                 immediately after the request bytes (ping-pong).
 *
 * CS handling: software NSS (SPI always enabled) + PA4 monitored by EXTI4.
 *   - falling edge : start of transaction, reset RX assembly
 *   - rising edge  : end of transaction, stop accepting bytes
 * Response bytes are preloaded on frame completion so the first response
 * byte is clocked out on the clock right after the last request byte.
 */
#include "spi_slave.h"
#include "spi_proto.h"        /* 帧协议层（纯逻辑，可离线对拍）*/
#include "sim_util.h"
#include "sim_at.h"
#include "sim_cfg.h"
#include "sim_wifi.h"
#include "board.h"
#include "gpio.h"
#include "uart.h"

/* ------------------------------------------------------------------ */
/* static state                                                       */
/* ------------------------------------------------------------------ */
/* 帧装配状态机（协议层）。`buf` 就在这个结构里，RAM 占用与原来单开一个
 * `s_rx_buf[1700]` 相同。*/
static spi_proto_rx_t s_rx;

static uint8_t  s_tx_buf[SPI_PROTO_MAX_FRAME + 8];
static uint16_t s_tx_len, s_tx_idx;

static uint8_t  s_at_resp[512];
static uint8_t  s_reset_req;

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */
static void irq_line_set(int level)
{
    gpio_set_pin(HOST_IRQ_PORT, HOST_IRQ_PIN, (uint8_t)level);
}

/* Build a response and preload the first byte so it is shifted out on the
 * first SCK of the next transaction. */
static void build_resp(uint8_t cmd, const uint8_t *payload, uint16_t len)
{
    /* 帧头+CRC+载荷都由协议层装（`out == payload` 也安全：DATA_RX 就是就地搬）*/
    uint16_t n = spi_proto_build_resp(s_tx_buf, sizeof(s_tx_buf), cmd, payload, len);
    if (n == 0) {                                    /* 缓冲不够：如实回 ERROR，不静默截断 */
        n = spi_proto_build_resp(s_tx_buf, sizeof(s_tx_buf), cmd, (const uint8_t *)"ERROR", 5);
    }
    s_tx_len = n;
    s_tx_idx = 1;                /* tx_buf[0] already preloaded into DATAR */
    HOST_SPI->DATAR = s_tx_buf[0];   /* preload */
}

static void build_err(uint8_t cmd)
{
    static const uint8_t err[] = "ERROR";
    build_resp(cmd, err, sizeof(err) - 1);
}

static void build_ok(uint8_t cmd)
{
    static const uint8_t ok[] = "OK";
    build_resp(cmd, ok, sizeof(ok) - 1);
}

/* ------------------------------------------------------------------ */
/* command dispatch                                                    */
/* ------------------------------------------------------------------ */
static void process_frame(uint8_t cmd, const uint8_t *payload, uint16_t len)
{
    switch (cmd) {
    case SPI_PROTO_CMD_AT: {
        char line[SPI_PROTO_MAX_FRAME + 1];
        uint16_t n = len < SPI_PROTO_MAX_FRAME ? len : SPI_PROTO_MAX_FRAME;
        uint16_t i;
        for (i = 0; i < n; i++) line[i] = (char)payload[i];
        line[n] = '\0';
        /* strip trailing CR/LF if present */
        while (n > 0 && (line[n - 1] == '\r' || line[n - 1] == '\n')) line[--n] = '\0';
        sim_at_run(line, (char *)s_at_resp, sizeof(s_at_resp));
        build_resp(cmd, s_at_resp, (uint16_t)sim_strlen((const char *)s_at_resp));
        break;
    }
    case SPI_PROTO_CMD_GET_STATE: {
        struct sim_state st;
        sim_wifi_fill_state(&st);
        build_resp(cmd, (const uint8_t *)&st, sizeof(st));
        break;
    }
    case SPI_PROTO_CMD_DATA_TX:
        if (sim_wifi_send_data(payload, len) == 0) build_ok(cmd);
        else build_err(cmd);
        break;
    case SPI_PROTO_CMD_DATA_RX: {
        uint16_t flen = 0;
        if (sim_wifi_take_rx(s_tx_buf + 4, &flen) == 0) {
            build_resp(cmd, s_tx_buf + 4, flen);
        } else {
            build_err(cmd);
        }
        break;
    }
    case SPI_PROTO_CMD_EVENT: {
        char evt[96];
        if (sim_wifi_take_event(evt, sizeof(evt)) == 0) {
            build_resp(cmd, (const uint8_t *)evt, (uint16_t)sim_strlen(evt));
        } else {
            build_err(cmd);
        }
        break;
    }
    case SPI_PROTO_CMD_PING:
        build_resp(cmd, (const uint8_t *)"PONG", 4);
        break;
    case SPI_PROTO_CMD_RESET:
        build_ok(cmd);
        s_reset_req = 1;
        break;
    case SPI_PROTO_CMD_SET_CFG:
        if (len == sizeof(struct sim_cfg)) {
            sim_memcpy(sim_cfg_mutable(), payload, sizeof(struct sim_cfg));
            sim_cfg_mutable()->magic = SIM_CFG_MAGIC;
            sim_cfg_save();
            build_ok(cmd);
        } else {
            build_err(cmd);
        }
        break;
    case SPI_PROTO_CMD_GET_CFG:
        build_resp(cmd, (const uint8_t *)sim_cfg_get(), sizeof(struct sim_cfg));
        break;
    default:
        build_err(cmd);
        break;
    }
}

/* ------------------------------------------------------------------ */
/* ISR: receive bytes, assemble frames, respond                        */
/* ------------------------------------------------------------------ */
static void spi_on_rx_byte(uint8_t b)
{
    spi_rx_ev_t ev;

    /* TX: shift out response bytes (else 0xFF) */
    if (s_tx_idx < s_tx_len) {
        HOST_SPI->DATAR = s_tx_buf[s_tx_idx++];
    } else {
        HOST_SPI->DATAR = 0xFF;
    }

    /* 协议层装配（响应阶段的字节会被它自己按 `done` 忽略）*/
    ev = spi_proto_rx_byte(&s_rx, b);
    if (ev == SPI_RX_FRAME) {
        uint16_t plen = 0;
        const uint8_t *pl = spi_proto_rx_payload(&s_rx, &plen);
        process_frame(spi_proto_rx_cmd(&s_rx), pl, plen);
    } else if (ev == SPI_RX_BAD_CRC || ev == SPI_RX_TOO_LONG) {
        build_err(spi_proto_rx_cmd(&s_rx));
    }
}

static void spi1_irq(void)
{
    while (HOST_SPI->STATR & SPI_STATR_RXNE) {
        spi_on_rx_byte((uint8_t)(HOST_SPI->DATAR & 0xFF));
    }
}

/* CS (PA4) edge detection via EXTI4: software NSS model */
static void cs_edge(void)
{
    if (GPIOA->INDR & BIT(HOST_SPI_NSS_PIN)) {
        spi_proto_cs_end(&s_rx);      /* rising: end of transaction */
    } else {
        spi_proto_cs_start(&s_rx);    /* falling: start of transaction */
    }
}

SIM_IRQ void SPI1_IRQHandler(void)
{
    spi1_irq();
}

SIM_IRQ void EXTI4_IRQHandler(void)
{
    if (EXTI->PR & BIT(HOST_SPI_NSS_PIN)) {
        cs_edge();
        EXTI->PR = BIT(HOST_SPI_NSS_PIN);
    }
}

/* ------------------------------------------------------------------ */
/* init / poll                                                         */
/* ------------------------------------------------------------------ */
void spi_slave_init(void)
{
    RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_AFIO |
                      RCC_APB2Periph_SPI1;

    /* pins: PA4 CS in, PA5 SCK in, PA6 MISO out(AF), PA7 MOSI in */
    gpio_set_mode(GPIOA, HOST_SPI_NSS_PIN, GPIO_MODE_IN_FLOATING);
    gpio_set_mode(GPIOA, HOST_SPI_SCK_PIN, GPIO_MODE_IN_FLOATING);
    gpio_set_mode(GPIOA, HOST_SPI_MISO_PIN, GPIO_MODE_AF_PP_50MHZ);
    gpio_set_mode(GPIOA, HOST_SPI_MOSI_PIN, GPIO_MODE_IN_FLOATING);

    /* IRQ output (host data-ready) */
    gpio_set_mode(HOST_IRQ_PORT, HOST_IRQ_PIN, GPIO_MODE_OUT_PP_50MHZ);
    irq_line_set(0);

    /* SPI1 slave: Mode0, MSB first, 8-bit, software NSS (CS via EXTI) */
    HOST_SPI->CTLR1 = 0;
    HOST_SPI->CFGR1 = SPI_CFGR1_RXNEIE;
    HOST_SPI->CTLR1 = SPI_CTLR1_SPE | SPI_CTLR1_SSM | SPI_CTLR1_SSI;

    /* PA4 -> EXTI4, rising + falling, enable */
    AFIO->EXTICR[1] &= ~(0xFul << 0);            /* port A for EXTI4 */
    EXTI->FTENR |= BIT(HOST_SPI_NSS_PIN);
    EXTI->RTENR |= BIT(HOST_SPI_NSS_PIN);
    EXTI->PR    |= BIT(HOST_SPI_NSS_PIN);
    EXTI->INTENR |= BIT(HOST_SPI_NSS_PIN);
    NVIC_EnableIRQ(EXTI4_IRQn);

    s_rx.done = 1;               /* 未开始事务前：不接收（靠 CS 下降沿开门）*/
    s_tx_idx = s_tx_len = 0;
    s_reset_req = 0;

    NVIC_EnableIRQ(HOST_SPI_IRQn);
}

void spi_slave_poll(void)
{
    /* keep IRQ line reflecting pending host data/events */
    irq_line_set((sim_wifi_has_rx() || sim_wifi_has_event()) ? 1 : 0);
    if (s_reset_req) {
        s_reset_req = 0;
        NVIC_SystemReset();
    }
}

void spi_slave_notify(void)
{
    irq_line_set(1);
}
