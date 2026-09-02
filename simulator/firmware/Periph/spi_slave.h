/* spi_slave.h — SPI1 slave host interface (frame protocol, see
 * docs/spi_protocol.md) */
#ifndef __SPI_SLAVE_H__
#define __SPI_SLAVE_H__

#include <stdint.h>

void spi_slave_init(void);

/* service from main loop: update IRQ line state, handle deferred reset */
void spi_slave_poll(void);

/* raise IRQ line (data ready / event pending) */
void spi_slave_notify(void);

#endif /* __SPI_SLAVE_H__ */
