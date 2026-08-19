/* sim_led.c */
#include "sim_led.h"
#include "sim_util.h"
#include "sim_cfg.h"
#include "sim_wifi.h"
#include "board.h"
#include "gpio.h"

extern volatile uint32_t g_tick_ms;

static uint8_t s_btn_last;
static uint32_t s_btn_stable_ts;
static uint8_t s_btn_state;
static int8_t  s_btn_pressed;
static uint8_t s_dip_last;

static void led_set(GPIO_TypeDef *port, uint8_t pin, int on, int active_low)
{
    gpio_set_pin(port, pin, (uint8_t)(active_low ? !on : on));
}

static void conn_led(int on)
{
    led_set(LED_CONN_PORT, LED_CONN_PIN, on, LED_CONN_ACTIVE_LOW);
}

static void rssi_leds(int bars)
{
    static const struct { GPIO_TypeDef *p; uint8_t n; } pins[4] = {
        { LED_RSSI_PORT, LED_RSSI_PIN0 },
        { LED_RSSI_PORT, LED_RSSI_PIN1 },
        { LED_RSSI_PORT, LED_RSSI_PIN2 },
        { LED_RSSI_PORT, LED_RSSI_PIN3 },
    };
    int i;
    for (i = 0; i < 4; i++) {
        led_set(pins[i].p, pins[i].n, (i < bars), LED_RSSI_ACTIVE_LOW);
    }
}

static int rssi_to_bars(int rssi)
{
    int v = (rssi < 0) ? -rssi : 0;
    if (v <= 40) return 4;
    if (v <= 55) return 3;
    if (v <= 70) return 2;
    if (v <= 80) return 1;
    return 0;
}

void sim_led_init(void)
{
    gpio_set_mode(LED_CONN_PORT, LED_CONN_PIN, GPIO_MODE_OUT_PP_50MHZ);
    conn_led(0);
    gpio_set_mode(LED_RSSI_PORT, LED_RSSI_PIN0, GPIO_MODE_OUT_PP_50MHZ);
    gpio_set_mode(LED_RSSI_PORT, LED_RSSI_PIN1, GPIO_MODE_OUT_PP_50MHZ);
    gpio_set_mode(LED_RSSI_PORT, LED_RSSI_PIN2, GPIO_MODE_OUT_PP_50MHZ);
    gpio_set_mode(LED_RSSI_PORT, LED_RSSI_PIN3, GPIO_MODE_OUT_PP_50MHZ);
    rssi_leds(0);

    /* button: input pull-up (press -> low) */
    gpio_set_mode(BTN_CONNECT_PORT, BTN_CONNECT_PIN, GPIO_MODE_IN_PUPD);
    gpio_set_pin(BTN_CONNECT_PORT, BTN_CONNECT_PIN, 1);   /* pull-up */

    /* DIP: input pull-up (switch to GND -> 0) */
    gpio_set_mode(DIP_MODE_PORT, DIP_MODE_PIN0, GPIO_MODE_IN_PUPD);
    gpio_set_pin(DIP_MODE_PORT, DIP_MODE_PIN0, 1);
    gpio_set_mode(DIP_MODE_PORT1, DIP_MODE_PIN1, GPIO_MODE_IN_PUPD);
    gpio_set_pin(DIP_MODE_PORT1, DIP_MODE_PIN1, 1);

    s_btn_last = 1;
    s_btn_stable_ts = 0;
    s_btn_state = 1;
    s_btn_pressed = 0;
    s_dip_last = 0xFF;
}

static uint8_t btn_read(void)
{
    return (uint8_t)(gpio_get_pin(BTN_CONNECT_PORT, BTN_CONNECT_PIN) ? 1 : 0);
}

static uint8_t dip_read(void)
{
    uint8_t b0 = (uint8_t)(gpio_get_pin(DIP_MODE_PORT, DIP_MODE_PIN0) ? 0 : 1);
    uint8_t b1 = (uint8_t)(gpio_get_pin(DIP_MODE_PORT1, DIP_MODE_PIN1) ? 0 : 1);
    return (uint8_t)((b1 << 1) | b0);   /* 0=AP 1=STA 2=GROUP 3=APSTA */
}

void sim_led_poll(void)
{
    const struct sim_cfg *c = sim_cfg_get();
    uint8_t b = btn_read();
    uint8_t dip = dip_read();

    /* debounce button */
    if (b != s_btn_last) {
        s_btn_last = b;
        s_btn_stable_ts = g_tick_ms;
    } else if ((int32_t)(g_tick_ms - s_btn_stable_ts) >= 40 && b != s_btn_state) {
        s_btn_state = b;
        if (b == 0) {
            /* pressed: toggle pairing (like CONNECT/PAIR on T-Halow-RJ45) */
            sim_wifi_set_pairing(sim_wifi_pairing() ? 0 : 1);
            s_btn_pressed = 1;
        }
    }

    /* DIP mode change -> reconfigure */
    if (dip != s_dip_last) {
        s_dip_last = dip;
        if (dip <= SIM_MODE_GROUP) {
            if (dip != c->mode) {
                sim_cfg_set_mode(dip);
                sim_wifi_init();
            }
        }
    }

    /* RSSI LEDs */
    if (sim_wifi_conn_state() == SIM_CONN_CONNECTED) {
        if (c->mode == SIM_MODE_AP) {
            rssi_leds(sim_wifi_sta_count() > 0 ? 2 : 0);
        } else {
            rssi_leds(rssi_to_bars(sim_wifi_get_rssi(0)));
        }
    } else {
        rssi_leds(0);
    }

    /* CONN LED */
    if (sim_wifi_pairing()) {
        conn_led(((g_tick_ms / 150) & 1) ? 1 : 0);   /* fast blink */
    } else if (sim_wifi_conn_state() == SIM_CONN_CONNECTED) {
        conn_led(1);
    } else {
        conn_led(0);
    }
}
