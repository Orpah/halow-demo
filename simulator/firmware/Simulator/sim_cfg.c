/* sim_cfg.c */
#include "sim_cfg.h"
#include "sim_util.h"

static struct sim_cfg s_cfg;

static void cfg_defaults(struct sim_cfg *c)
{
    int i;
    static const uint8_t def_mac[6] = {0x4A, 0x06, 0x59, 0x7B, 0x6C, 0x98};

    c->magic    = SIM_CFG_MAGIC;
    c->mode     = SIM_MODE_STA;
    c->keymgmt  = SIM_KEY_NONE;
    c->bss_bw   = 8;
    c->chan_cnt = 1;
    c->chan_list[0] = 9080;
    for (i = 1; i < SIM_CHAN_MAX; i++) c->chan_list[i] = 0;
    c->txpower  = 20;
    c->tx_mcs   = 255;
    c->heart_int = 500;
    c->ack_tmo  = 0;
    c->roam     = 0;
    c->ps_mode  = 0;
    for (i = 0; i < SIM_MAC_LEN; i++) c->mac[i] = def_mac[i];
    c->ssid_len = 0;
    c->ssid[0]  = '\0';
    c->psk[0]   = '\0';
    c->r_ssid_len = 0;
    c->r_ssid[0]  = '\0';
    c->r_psk[0]   = '\0';
    c->rssi     = -30;
    for (i = 0; i < 6; i++) c->group[i] = 0;
    c->aid      = 0;
}

const struct sim_cfg *sim_cfg_get(void) { return &s_cfg; }
struct sim_cfg *sim_cfg_mutable(void)   { return &s_cfg; }

void sim_cfg_init(void)
{
    /* RAM-only config by default. To persist across power-cycles, implement
     * a FLASH read here and in sim_cfg_save() (see below). */
    cfg_defaults(&s_cfg);
}

void sim_cfg_reset(void)
{
    cfg_defaults(&s_cfg);
    sim_cfg_save();
}

/* Persistence is optional. To enable: write s_cfg to the last flash page
 * (CH32V203: page size 1KB, last page @ 0x0800FC00) and restore on boot.
 * Implement with the WCH FLASH controller registers (FLASH_Unlock / erase /
 * program halfword). Disabled by default to keep the simulator safe. */
__attribute__((weak)) void sim_cfg_save(void)
{
    /* no-op */
}

int sim_cfg_set_mode(int m)
{
    if (m < SIM_MODE_AP || m > SIM_MODE_GROUP) return -1;
    s_cfg.mode = (uint8_t)m;
    sim_cfg_save();
    return 0;
}

int sim_cfg_set_ssid(const char *s)
{
    int n = sim_strlen(s);
    if (n <= 0 || n > SIM_SSID_MAX) return -1;
    sim_strlcpy(s_cfg.ssid, s, SIM_SSID_MAX + 1);
    s_cfg.ssid_len = (uint8_t)n;
    sim_cfg_save();
    return 0;
}

int sim_cfg_set_psk(const char *s)
{
    int n = sim_strlen(s);
    if (n != 64) return -1;
    sim_strlcpy(s_cfg.psk, s, 65);
    s_cfg.keymgmt = SIM_KEY_WPA_PSK;
    sim_cfg_save();
    return 0;
}

int sim_cfg_set_chan_list(const uint16_t *list, int cnt)
{
    int i;
    if (cnt < 1 || cnt > SIM_CHAN_MAX) return -1;
    for (i = 0; i < cnt; i++) {
        if (list[i] < 1000 || list[i] > 20000) return -1;
    }
    for (i = 0; i < cnt; i++) s_cfg.chan_list[i] = list[i];
    s_cfg.chan_cnt = (uint8_t)cnt;
    sim_cfg_save();
    return 0;
}

int sim_cfg_chan_in_list(uint16_t freq)
{
    int i;
    for (i = 0; i < s_cfg.chan_cnt; i++) {
        if (s_cfg.chan_list[i] == freq) return 1;
    }
    return 0;
}
