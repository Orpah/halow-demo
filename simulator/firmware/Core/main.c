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
    TIM2->PSC = SYSTEM_CLOCK_HZ / 1000 - 1;   /* -> 1 kHz */
    TIM2->ATRLR = 0;                          /* period = 1 ms */
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
    /* data-mode (AT+TXDATA): raw bytes go straight to the frame buffer */
    if (sim_at_txdata_active()) {
        sim_at_data_byte(b);
        return;
    }

    if (b == '\n') {
        if (s_line_len > 0) {
            s_line[s_line_len] = '\0';
            sim_at_run(s_line, NULL, 0);
            s_line_len = 0;
        }
        return;
    }
    if (b == '\r') {
        return;
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
