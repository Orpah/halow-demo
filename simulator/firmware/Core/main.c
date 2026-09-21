/* main.c — TXW8301 Simulator (CH32V203)
 *
 * Bare-metal, no OS. 8 MHz HSI. TIM2 provides a 1 ms tick.
 */
#include "ch32v20x.h"
#include "board.h"
#include "gpio.h"
#include "uart.h"
#include "spi_slave.h"
#include "sim_util.h"
#include "sim_cfg.h"
#include "sim_wifi.h"
#include "sim_at.h"
#include "sim_link.h"
#include "sim_led.h"

/* ------------------------------------------------------------------ */
/* 1 ms tick                                                          */
/* ------------------------------------------------------------------ */
volatile uint32_t g_tick_ms;

static void tick_init(void)
{
    RCC->APB1PCENR |= RCC_APB1Periph_TIM2;

    TIM2->CTLR1 = 0;
    TIM2->PSC = SYSTEM_CLOCK_HZ / 1000000UL - 1UL;   /* -> 1 MHz 计数时钟 */
    TIM2->ATRLR = 1000UL - 1UL;                      /* -> 1000 计数 = 1 ms */
    TIM2->CNT   = 0u;
    /* ★ `INTFR` 是 **write-all-bits**：清标志要**写 0**（写 1 反而置位 ⇒ ISR 死风暴；
     *   依据 WCH `TIM_ClearITPendingBit(): TIMx->INTFR = (uint16_t)~TIM_IT;`）。
     *   写 `EVGR=UG` 让 PSC/ARR 立刻生效。*/
    TIM2->EVGR  = 1u;
    TIM2->INTFR = 0u;
    TIM2->DMAINTENR |= TIM_DMAINTENR_UIE;
    TIM2->CTLR1 |= TIM_CTLR1_CEN | TIM_CTLR1_ARPE;
    NVIC_EnableIRQ(TIM2_IRQn);
}

SIM_IRQ void TIM2_IRQHandler(void)
{
    TIM2->INTFR &= ~TIM_INTFR_UIF;
    g_tick_ms++;
}

/* ------------------------------------------------------------------ */
/* UART IRQs                                                          */
/* ------------------------------------------------------------------ */
SIM_IRQ void USART1_IRQHandler(void)
{
    uart_irq_rx(USART1);
}

SIM_IRQ void USART2_IRQHandler(void)
{
    uart_irq_rx(USART2);
}

/* ------------------------------------------------------------------ */
/* Console (UART1) line handler                                       */
/* ------------------------------------------------------------------ */
#define CONSOLE_LINE_MAX 256
static char  s_line[CONSOLE_LINE_MAX];
static uint16_t s_line_len;

static void console_on_byte(uint8_t b)
{
    /* data-mode (AT+TXDATA): raw bytes go straight to the frame buffer
     * ★ 必须放在最前面 —— 数据面是**二进制裸帧**，绝不能当行处理、也不能回显。*/
    if (sim_at_txdata_active()) {
        sim_at_data_byte(b);
        return;
    }

    /* ★★ 2026-09-21 上机加固（原来只认 `\n`，`\r` 被丢弃**且不清行缓冲**）：
     *   ① **`\r` 与 `\n` 都当行尾** ⇒ 终端行尾设置不再敏感；CRLF 时尾随的 `\n`
     *      会被下面的 `s_line_len > 0` 自然忽略（不会执行一条空命令）。
     *      背景（实测踩到）：用只会发 CR 的终端（PuTTY 默认）时 `AT` 毫无反应，
     *      而残留的行缓冲会把下一条命令粘成 `ATAT` ⇒ 回 `ERROR`。
     *   ② **回显可打印字符** ⇒ 原来不回显，敲字屏幕上不动，很容易被当成"串口坏了"。*/
    if (b == '\r' || b == '\n') {
        if (s_line_len > 0) {
            s_line[s_line_len] = '\0';
            uart_printf(CONSOLE_UART, "\r\n");  /* 响应从新行开始（输入已在上面回显）*/
            sim_at_run(s_line, NULL, 0);
            s_line_len = 0;
        }
        return;
    }
    if (b >= 0x20u && b < 0x7Fu) {
        uart_putc(CONSOLE_UART, b);             /* 回显（只回显可打印字符）*/
    }
    if (s_line_len < CONSOLE_LINE_MAX - 1) {
        s_line[s_line_len++] = (char)b;
    }
}

/* ------------------------------------------------------------------ */
/* SystemInit (called from startup before main)                       */
/* ------------------------------------------------------------------ */
void SystemInit(void)
{
    /* HSI 8 MHz is the default after reset; nothing to configure.
     * To use HSE/PLL, enable HSE in RCC->CTLR, wait ready, configure
     * RCC->CFGR0 and FLASH wait states here. */
}

/* ------------------------------------------------------------------ */
/* boot banner                                                        */
/* ------------------------------------------------------------------ */
static void print_banner(void)
{
    uart_printf(CONSOLE_UART, "\r\n");
    uart_printf(CONSOLE_UART, "TXW8301 Simulator v0.1.0 (CH32V203, no RF)\r\n");
    uart_printf(CONSOLE_UART, "AT console ready. Type 'AT' to test.\r\n");
}

/* ------------------------------------------------------------------ */
/* main                                                               */
/* ------------------------------------------------------------------ */
int main(void)
{
    uint32_t last_5ms = 0;
    uint32_t last_stats = 0;

    /* clocks for GPIO/AFIO */
    RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOB |
                      RCC_APB2Periph_GPIOC | RCC_APB2Periph_AFIO;

    /* console UART1 (CH340C) */
    uart_init(CONSOLE_UART, GPIOA, CONSOLE_TX_PIN, CONSOLE_RX_PIN,
              CONSOLE_BAUD, CONSOLE_UART_IRQn, console_on_byte);

    /* simulator modules */
    sim_cfg_init();
    sim_wifi_init();
    sim_link_init();          /* UART2 virtual air */
    sim_led_init();
    spi_slave_init();         /* SPI1 host interface */

    tick_init();

    print_banner();

    for (;;) {
        if ((int32_t)(g_tick_ms - last_5ms) >= 5) {
            last_5ms = g_tick_ms;
            sim_wifi_poll();
            sim_link_poll();
            sim_led_poll();
        }

        spi_slave_poll();

        /* optional debug stats */
        if ((sim_at_dbg_lmac() || sim_at_dbg_wnb()) &&
            (int32_t)(g_tick_ms - last_stats) >= 1000) {
            last_stats = g_tick_ms;
            if (sim_at_dbg_wnb()) {
                uart_printf(CONSOLE_UART,
                            "WNB: tx=%u rx=%u stacnt=%d state=%s\r\n",
                            sim_wifi_tx_pkts(), sim_wifi_rx_pkts(),
                            sim_wifi_sta_count(), sim_wifi_conn_str());
            }
            if (sim_at_dbg_lmac()) {
                uart_printf(CONSOLE_UART,
                            "LMAC: link_tx=%u link_rx=%u\r\n",
                            sim_link_tx_pkts(), sim_link_rx_pkts());
            }
        }
    }
}
