/* sim_link.h — virtual air link over UART2 (cross-link between simulators) */
#ifndef __SIM_LINK_H__
#define __SIM_LINK_H__

#include <stdint.h>
#include "sim_cfg.h"

#define SIM_LINK_MAX  1700

void sim_link_init(void);
void sim_link_poll(void);   /* call from main loop; delivers frames */

/* Send a frame to peer(s): [0xAA 0x55 TYPE LEN_H LEN_L CRC8 PAYLOAD...] */
void sim_link_send(uint8_t type, const uint8_t *payload, uint16_t len);

/* Called when a complete frame is received (main loop context) */
void sim_link_handle_frame(uint8_t type, const uint8_t *payload, uint16_t len);

/* stats for AT+SYSDBG */
uint32_t sim_link_tx_pkts(void);
uint32_t sim_link_rx_pkts(void);

#endif /* __SIM_LINK_H__ */
