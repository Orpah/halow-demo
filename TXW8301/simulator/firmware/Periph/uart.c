/* uart.c — interrupt-driven USART driver (USART1/2) */
#include "uart.h"
#include "board.h"
#include "gpio.h"

#define UART_MAX_INST 2

static uart_rx_cb s_cb[UART_MAX_INST];
static USART_TypeDef *s_uart[UART_MAX_INST];
static uint8_t s_cnt = 0;

static int uart_index(USART_TypeDef *u)
{
    int i;
    for (i = 0; i < s_cnt; i++) {
        if (s_uart[i] == u) return i;
    }
    return -1;
}

static int sim_strlen(const char *s)
{
    int n = 0;
    while (s && s[n]) n++;
    return n;
}

void uart_init(USART_TypeDef *uart, GPIO_TypeDef *port,
               uint8_t tx_pin, uint8_t rx_pin,
               uint32_t baud, IRQn_Type irqn, uart_rx_cb cb)
{
    int idx = uart_index(uart);

    if (idx < 0 && s_cnt < UART_MAX_INST) {
        idx = s_cnt;
        s_uart[idx] = uart;
        s_cb[idx] = cb;
        s_cnt++;
    }

    /* TX = AF push-pull, RX = input floating */
    gpio_set_mode(port, tx_pin, GPIO_MODE_AF_PP_50MHZ);
    gpio_set_mode(port, rx_pin, GPIO_MODE_IN_FLOATING);

    /* baud = PCLK / baud; both USARTs on 8 MHz bus */
    uart->BRR = (SYSTEM_CLOCK_HZ + baud / 2) / baud;

    /* UE | RE | TE | RXNEIE */
    uart->CTLR1 = USART_CTLR1_UE | USART_CTLR1_RE | USART_CTLR1_TE |
                  USART_CTLR1_RXNEIE;

    NVIC_EnableIRQ(irqn);
}

void uart_putc(USART_TypeDef *uart, uint8_t c)
{
    while (!(uart->STATR & USART_FLAG_TXE)) { }
    uart->DATAR = c;
}

void uart_write(USART_TypeDef *uart, const uint8_t *data, uint32_t len)
{
    uint32_t i;
    for (i = 0; i < len; i++) {
        uart_putc(uart, data[i]);
    }
}

void uart_printf(USART_TypeDef *uart, const char *fmt, ...)
{
    char buf[128];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = 0;
    {
        /* minimal vsnprintf replacement (no libc on some toolchains) */
        const char *p = fmt;
        int j = 0;
        for (; *p && j < (int)sizeof(buf) - 1; p++) {
            if (*p == '%') {
                p++;
                if (*p == 's') {
                    const char *s = va_arg(ap, const char *);
                    if (!s) s = "(null)";
                    while (*s && j < (int)sizeof(buf) - 1) buf[j++] = *s++;
                } else if (*p == 'd' || *p == 'i') {
                    int v = va_arg(ap, int);
                    char tmp[12];
                    int k = 0;
                    unsigned int u = (v < 0) ? (unsigned int)(-v) : (unsigned int)v;
                    if (v < 0) tmp[k++] = '-';
                    do { tmp[k++] = (char)('0' + u % 10); u /= 10; } while (u);
                    while (k > 0) buf[j++] = tmp[--k];
                } else if (*p == 'u') {
                    unsigned int u = va_arg(ap, unsigned int);
                    char tmp[12];
                    int k = 0;
                    do { tmp[k++] = (char)('0' + u % 10); u /= 10; } while (u);
                    while (k > 0) buf[j++] = tmp[--k];
                } else if (*p == 'x' || *p == 'X') {
                    unsigned int u = va_arg(ap, unsigned int);
                    char tmp[12];
                    int k = 0;
                    const char *hex = "0123456789abcdef";
                    do { tmp[k++] = hex[u & 0xF]; u >>= 4; } while (u);
                    while (k > 0) buf[j++] = tmp[--k];
                } else if (*p == 'c') {
                    buf[j++] = (char)va_arg(ap, int);
                } else if (*p == '%') {
                    buf[j++] = '%';
                } else {
                    buf[j++] = '%';
                    buf[j++] = *p;
                }
            } else {
                buf[j++] = *p;
            }
        }
        buf[j] = '\0';
        n = j;
    }
    va_end(ap);
    (void)n;
    uart_write(uart, (const uint8_t *)buf, (uint32_t)sim_strlen(buf));
}

void uart_irq_rx(USART_TypeDef *uart)
{
    int idx = uart_index(uart);
    uint8_t b;

    while (uart->STATR & USART_FLAG_RXNE) {
        b = (uint8_t)(uart->DATAR & 0xFF);
        if (idx >= 0 && s_cb[idx]) {
            s_cb[idx](b);
        }
    }
}
