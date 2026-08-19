/* uart.h */
#ifndef __UART_H__
#define __UART_H__

#include "ch32v20x.h"
#include <stdarg.h>

typedef void (*uart_rx_cb)(uint8_t byte);

/* Init a USART (8N1), enable RX interrupt, register byte callback. */
void uart_init(USART_TypeDef *uart, GPIO_TypeDef *port,
               uint8_t tx_pin, uint8_t rx_pin,
               uint32_t baud, IRQn_Type irqn, uart_rx_cb cb);

void uart_putc(USART_TypeDef *uart, uint8_t c);
void uart_write(USART_TypeDef *uart, const uint8_t *data, uint32_t len);
void uart_printf(USART_TypeDef *uart, const char *fmt, ...);

/* Called from USART1/2 IRQ handlers */
void uart_irq_rx(USART_TypeDef *uart);

#endif /* __UART_H__ */
