/* sim_wifi.h — simulated HaLow wireless state machine */
#ifndef __SIM_WIFI_H__
#define __SIM_WIFI_H__

#include <stdint.h>
#include "sim_cfg.h"

#define SIM_RX_QUEUE     4
#define SIM_EVT_QUEUE    4
#define SIM_MAX_FRAME    1700
#define SIM_MAX_STA      8

void sim_wifi_init(void);
void sim_wifi_poll(void);          /* periodic tick (call every ~5ms) */

/* host data path */
int  sim_wifi_send_data(const uint8_t *frame, uint16_t len);
int  sim_wifi_take_rx(uint8_t *buf, uint16_t *len);
int  sim_wifi_take_event(char *buf, uint16_t size);
/* non-destructive probes (for IRQ line management) */
int  sim_wifi_has_rx(void);
int  sim_wifi_has_event(void);

/* link callback (from sim_link_poll) */
void sim_link_handle_frame(uint8_t type, const uint8_t *payload, uint16_t len);

/* queries used by AT engine */
int  sim_wifi_conn_state(void);
const char *sim_wifi_conn_str(void);
int  sim_wifi_sta_count(void);
int  sim_wifi_get_rssi(int index);         /* 0 = first */
int  sim_wifi_pairing(void);
void sim_wifi_set_pairing(int on);
int  sim_wifi_mode(void);

/* WNB/LMAC debug counters */
uint32_t sim_wifi_tx_pkts(void);
uint32_t sim_wifi_rx_pkts(void);

/* last seen AP (from BEACON) for AT+BSSLIST; returns 1 if seen */
int sim_wifi_last_ap(char *ssid, uint16_t *freq, uint8_t *bw, int8_t *rssi);

/* runtime state snapshot for GET_STATE */
void sim_wifi_fill_state(struct sim_state *st);

#endif /* __SIM_WIFI_H__ */
