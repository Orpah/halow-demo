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
/* SPI host 协议常量（帧格式/命令字）**不在这里** —— 单一源是协议层：          */
/*   `firmware/Simulator/spi_proto.h`（纯逻辑，可与主机侧 tools/spi_frame.py   */
/*   离线对拍：python tools/check_spi_proto.py）。别在本文件再抄一份：         */
/*   两份漂移了不会报错，只会在真机上表现为“发出去没反应”。                    */
/* 本文件只管**引脚/端口**（见上面 HOST_SPI_* / HOST_IRQ_*）。                  */
/* ------------------------------------------------------------------ */

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
