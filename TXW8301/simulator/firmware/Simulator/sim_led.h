/* sim_led.h — LEDs (CONN + RSSI x4), CONNECT button, mode DIP switch */
#ifndef __SIM_LED_H__
#define __SIM_LED_H__

void sim_led_init(void);
void sim_led_poll(void);   /* call every ~5ms */

#endif /* __SIM_LED_H__ */
