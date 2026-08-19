/* sim_cfg.h — simulator configuration (mirrors TXW8301 syscfg subset) */
#ifndef __SIM_CFG_H__
#define __SIM_CFG_H__

#include <stdint.h>

#define SIM_SSID_MAX      32
#define SIM_CHAN_MAX      16
#define SIM_MAC_LEN       6

/* operating mode */
#define SIM_MODE_AP       0
#define SIM_MODE_STA      1
#define SIM_MODE_APSTA    2
#define SIM_MODE_GROUP    3

/* key management */
#define SIM_KEY_NONE      0
#define SIM_KEY_WPA_PSK   1

/* connection state */
#define SIM_CONN_IDLE          0
#define SIM_CONN_SCANNING      1
#define SIM_CONN_ASSOCIATING   2
#define SIM_CONN_CONNECTED     3
#define SIM_CONN_DISCONNECTED  4

/* link frame types (virtual air) */
#define SIM_LINK_TYPE_DATA       0x01
#define SIM_LINK_TYPE_BEACON     0x02
#define SIM_LINK_TYPE_ASSOC_REQ  0x03
#define SIM_LINK_TYPE_ASSOC_RESP 0x04
#define SIM_LINK_TYPE_PAIR_PSK   0x05
#define SIM_LINK_TYPE_DEAUTH     0x06

#define SIM_VERSION_STR "TXW8301-SIM-v0.1.0 (CH32V203)"

struct sim_cfg {
    uint32_t magic;             /* CFG_MAGIC if valid */
    uint8_t  mode;              /* SIM_MODE_* */
    uint8_t  keymgmt;           /* SIM_KEY_* */
    uint8_t  bss_bw;            /* 1/2/4/8 MHz */
    uint8_t  chan_cnt;
    uint16_t chan_list[SIM_CHAN_MAX]; /* frequency x0.1MHz */
    uint8_t  txpower;           /* 6..20 dBm */
    uint8_t  tx_mcs;            /* 0..7, 255 auto */
    uint16_t heart_int;         /* ms */
    uint16_t ack_tmo;           /* us */
    uint8_t  roam;              /* 0/1 */
    uint8_t  ps_mode;           /* 0..4 */
    uint8_t  mac[SIM_MAC_LEN];
    uint8_t  ssid_len;
    char     ssid[SIM_SSID_MAX];
    char     psk[65];           /* 64 hex chars */
    uint8_t  r_ssid_len;
    char     r_ssid[SIM_SSID_MAX];
    char     r_psk[65];
    int8_t   rssi;              /* -dBm */
    uint8_t  group[6];
    uint8_t  aid;
};

#define SIM_CFG_MAGIC 0x53494D31u   /* "SIM1" */

/* runtime (non-persistent) state, readable via GET_STATE */
struct sim_state {
    uint8_t  mode;
    uint8_t  conn_state;
    uint8_t  sta_cnt;
    int8_t   rssi;
    uint8_t  pairing;
    uint8_t  encrypt;
    uint8_t  mac[6];
    uint8_t  ssid_len;
    char     ssid[32];
    uint16_t chan_list[16];
    uint8_t  chan_cnt;
    uint8_t  bss_bw;
    uint32_t up_time_ms;
};

const struct sim_cfg *sim_cfg_get(void);
struct sim_cfg *sim_cfg_mutable(void);

void sim_cfg_init(void);         /* load defaults (RAM only by default) */
void sim_cfg_reset(void);        /* restore defaults */
void sim_cfg_save(void);         /* persistence hook (weak, no-op unless enabled) */

/* helpers */
int  sim_cfg_set_mode(int m);
int  sim_cfg_set_ssid(const char *s);
int  sim_cfg_set_psk(const char *s);
int  sim_cfg_set_chan_list(const uint16_t *list, int cnt);
int  sim_cfg_chan_in_list(uint16_t freq);

#endif /* __SIM_CFG_H__ */
