/* gpio.c */
#include "gpio.h"

void gpio_set_mode(GPIO_TypeDef *port, uint8_t pin, uint32_t mode)
{
    volatile uint32_t *reg = (pin < 8) ? &port->CFGLR : &port->CFGHR;
    uint8_t shift = (pin & 0x07) * 4;
    uint32_t mask = 0xFul << shift;

    *reg = (*reg & ~mask) | ((mode & 0xFul) << shift);
}
