/* board.h — TXW8301 Simulator board configuration
 *
 * CH32V203C8T6 (LQFP48). See docs/hardware.md for the full pin map.
 */
#ifndef __BOARD_H__
#define __BOARD_H__

#include "ch32v20x.h"

/* ------------------------------------------------------------------ */
/* Clock                                                               */
/* ------------------------------------------------------------------ */
#define SYSTEM_CLOCK_HZ      8000000UL   /* HSI 8MHz, no PLL */

/* ------------------------------------------------------------------ */
/* UART1 = AT console (CH340C)                                         */
/* ------------------------------------------------------------------ */
#define CONSOLE_UART         USART1
#define CONSOLE_UART_IRQn    USART1_IRQn
#define CONSOLE_UART_IRQ     USART1_IRQHandler
#define CONSOLE_BAUD         115200UL
#define CONSOLE_TX_PIN       9           /* PA9  (AF PP) */
#define CONSOLE_RX_PIN       10          /* PA10 (input) */

/* ------------------------------------------------------------------ */
/* UART2 = virtual air link (cross-link to peer simulator)             */
/* ------------------------------------------------------------------ */
#define LINK_UART            USART2
#define LINK_UART_IRQn       USART2_IRQn
#define LINK_UART_IRQ        USART2_IRQHandler
#define LINK_BAUD            115200UL
#define LINK_TX_PIN          2           /* PA2  (AF PP) */
#define LINK_RX_PIN          3           /* PA3  (input) */

/* ------------------------------------------------------------------ */
/* SPI1 = host interface (slave)                                       */
/* ------------------------------------------------------------------ */
#define HOST_SPI             SPI1
#define HOST_SPI_IRQn        SPI1_IRQn
#define HOST_SPI_IRQ         SPI1_IRQHandler
#define HOST_SPI_PORT        GPIOA
#define HOST_SPI_NSS_PIN     4           /* PA4 NSS (input) */
#define HOST_SPI_SCK_PIN     5           /* PA5 SCK (input) */
#define HOST_SPI_MISO_PIN    6           /* PA6 MISO (AF PP) */
#define HOST_SPI_MOSI_PIN    7           /* PA7 MOSI (input) */

/* IRQ line to host (data-ready / event), active high */
#define HOST_IRQ_PORT        GPIOB
#define HOST_IRQ_PIN         0           /* PB0 (output) */

/* ------------------------------------------------------------------ */
/* LEDs                                                                */
/* ------------------------------------------------------------------ */
#define LED_CONN_PORT        GPIOC
#define LED_CONN_PIN         13          /* PC13, ACTIVE LOW */
#define LED_CONN_ACTIVE_LOW  1

#define LED_RSSI_PORT        GPIOB
#define LED_RSSI_PIN0        6           /* PB6 */
#define LED_RSSI_PIN1        7           /* PB7 */
#define LED_RSSI_PIN2        8           /* PB8 */
#define LED_RSSI_PIN3        9           /* PB9 */
#define LED_RSSI_ACTIVE_LOW  0

/* ------------------------------------------------------------------ */
/* Inputs                                                              */
/* ------------------------------------------------------------------ */
#define BTN_CONNECT_PORT     GPIOA
#define BTN_CONNECT_PIN      0           /* PA0, active low (pull-up) */

#define DIP_MODE_PORT        GPIOA
#define DIP_MODE_PIN0        1           /* PA1 */
#define DIP_MODE_PORT1       GPIOB
#define DIP_MODE_PIN1        5           /* PB5 */
/* DIP: 00=AP 01=STA 10=GROUP 11=APSTA (switched to GND => 0) */

/* ------------------------------------------------------------------ */
/* SPI host protocol constants (see docs/spi_protocol.md)              */
/* ------------------------------------------------------------------ */
#define SIM_SPI_MAX_FRAME    1700        /* align DATA_AREA_SIZE */
#define SIM_SPI_CMD_AT       0x01
#define SIM_SPI_CMD_GET_STATE 0x02
#define SIM_SPI_CMD_DATA_TX  0x03
#define SIM_SPI_CMD_DATA_RX  0x04
#define SIM_SPI_CMD_EVENT    0x05
#define SIM_SPI_CMD_PING     0x06
#define SIM_SPI_CMD_RESET    0x07
#define SIM_SPI_CMD_SET_CFG  0x08
#define SIM_SPI_CMD_GET_CFG  0x09
#define SIM_SPI_RESP_FLAG    0x80

/* ------------------------------------------------------------------ */
/* Interrupt handler attribute                                        */
/* ------------------------------------------------------------------ */
#if defined(__riscv) && defined(WCH_INTERRUPT_FAST)
#define SIM_IRQ __attribute__((interrupt("WCH-Interrupt-fast")))
#elif defined(__riscv)
#define SIM_IRQ __attribute__((interrupt))
#else
#define SIM_IRQ
#endif

#endif /* __BOARD_H__ */
