/* gpio.h */
#ifndef __GPIO_H__
#define __GPIO_H__

#include "ch32v20x.h"

/* Configure one pin (0..15) of a port with a CRL/CRH mode value */
void gpio_set_mode(GPIO_TypeDef *port, uint8_t pin, uint32_t mode);

static inline void gpio_set_pin(GPIO_TypeDef *port, uint8_t pin, uint8_t level)
{
    if (level) port->BSHR = BIT(pin);
    else       port->BCHR = BIT(pin);
}

static inline uint8_t gpio_get_pin(GPIO_TypeDef *port, uint8_t pin)
{
    return (uint8_t)((port->INDR >> pin) & 1u);
}

#endif /* __GPIO_H__ */
