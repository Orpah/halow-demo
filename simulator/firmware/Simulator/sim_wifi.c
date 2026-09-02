/* sim_wifi.c — simulated HaLow wireless state machine
 *
 * AP  : periodically broadcasts BEACON; accepts ASSOC_REQ, tracks STAs.
 * STA : listens for BEACON, sends ASSOC_REQ, becomes CONNECTED on ASSOC_RESP.
 * DATA: frames from the SPI host are sent over the virtual air link; frames
 *       addressed to us (unicast/broadcast/group) are queued for the host.
 */
#include "sim_wifi.h"
#include "sim_util.h"
#include "sim_link.h"
#include "sim_cfg.h"
#include "board.h"
#include "spi_slave.h"
#include "uart.h"

extern volatile uint32_t g_tick_ms;   /* 1 ms tick from TIM2 */

/* ------------------------------------------------------------------ */
/* static state                                                       */
/* ------------------------------------------------------------------ */
static struct {
    uint8_t  conn;               /* SIM_CONN_* */
    uint8_t  pairing;
    uint8_t  scan_busy;
    uint32_t next_beacon;        /* AP beacon tick */
    uint32_t next_retry;         /* STA assoc retry tick */
    uint32_t next_keepalive;     /* STA keepalive tick */
    uint32_t last_peer_ts;       /* last beacon/assoc received */
    uint32_t tx_pkts, rx_pkts;

    /* STA table (AP mode) */
    uint8_t  sta_mac[SIM_MAX_STA][6];
    int8_t   sta_rssi[SIM_MAX_STA];
    uint8_t  sta_cnt;

    /* last seen AP (for BSSLIST) */
    uint8_t  has_ap;
    char     ap_ssid[33];
    uint16_t ap_freq;
    uint8_t  ap_bw;
    int8_t   ap_rssi;
} S;

/* rx frame ring (frames from peer addressed to us) */
static uint8_t  s_rx_data[SIM_RX_QUEUE][SIM_MAX_FRAME];
static uint16_t s_rx_len[SIM_RX_QUEUE];
static uint8_t  s_rx_head, s_rx_tail, s_rx_cnt;

/* event ring (async +XXX strings) */
static char     s_evt[SIM_EVT_QUEUE][96];
static uint8_t  s_evt_head, s_evt_tail, s_evt_cnt;

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */
static int mac_is_bcast(const uint8_t *m)
{
    int i;
    for (i = 0; i < 6; i++) if (m[i] != 0xFF) return 0;
    return 1;
}

static int mac_is_me(const uint8_t *m)
{
    const struct sim_cfg *c = sim_cfg_get();
    return sim_memcmp(m, c->mac, 6) == 0;
}

static int mac_is_group(const uint8_t *m)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (c->mode == SIM_MODE_GROUP) {
        return sim_memcmp(m, c->group, 6) == 0;
    }
    return (m[0] & 0x01) != 0;   /* multicast bit */
}

static void emit(const char *text)
{
    if (s_evt_cnt < SIM_EVT_QUEUE) {
        sim_strlcpy(s_evt[s_evt_tail], text, sizeof(s_evt[0]));
        s_evt_tail = (uint8_t)((s_evt_tail + 1) % SIM_EVT_QUEUE);
        s_evt_cnt++;
    }
    uart_printf(CONSOLE_UART, "%s\r\n", text);
    spi_slave_notify();          /* raise IRQ so host reads event */
}

int sim_wifi_mode(void) { return sim_cfg_get()->mode; }
int sim_wifi_conn_state(void) { return S.conn; }
int sim_wifi_pairing(void) { return S.pairing; }
void sim_wifi_set_pairing(int on) { S.pairing = on ? 1 : 0; }
int sim_wifi_sta_count(void) { return S.sta_cnt; }
uint32_t sim_wifi_tx_pkts(void) { return S.tx_pkts; }
uint32_t sim_wifi_rx_pkts(void) { return S.rx_pkts; }

const char *sim_wifi_conn_str(void)
{
    switch (S.conn) {
    case SIM_CONN_IDLE:          return "IDLE";
    case SIM_CONN_SCANNING:      return "SCANNING";
    case SIM_CONN_ASSOCIATING:   return "ASSOCIATING";
    case SIM_CONN_CONNECTED:     return "CONNECTED";
    case SIM_CONN_DISCONNECTED:  return "DISCONNECTED";
    default:                     return "UNKNOWN";
    }
}

int sim_wifi_get_rssi(int index)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (c->mode == SIM_MODE_AP) {
        if (index < 0 || index >= S.sta_cnt) return 0;
        return S.sta_rssi[index];
    }
    return (S.conn == SIM_CONN_CONNECTED) ? (int)c->rssi : 0;
}

/* ------------------------------------------------------------------ */
/* link handling                                                      */
/* ------------------------------------------------------------------ */
void sim_link_handle_frame(uint8_t type, const uint8_t *payload, uint16_t len)
{
    const struct sim_cfg *c = sim_cfg_get();

    switch (type) {
    case SIM_LINK_TYPE_BEACON: {
        /* payload: ssid_len, ssid[..], freq_h, freq_l, bw, enc */
        if (c->mode != SIM_MODE_STA && c->mode != SIM_MODE_APSTA) break;
        if (len < 5) break;
        uint8_t ssid_len = payload[0];
        uint16_t freq = (uint16_t)((payload[ssid_len + 1] << 8) | payload[ssid_len + 2]);
        uint8_t bw = payload[ssid_len + 3];
        uint8_t enc = payload[ssid_len + 4];
        int match;

        if (ssid_len > 32 || len < (uint16_t)(5 + ssid_len)) break;

        /* SSID match: if we have a configured SSID it must equal the AP's;
         * if none (pairing) accept any. */
        match = 0;
        if (c->ssid_len == 0) match = 1;
        else if (c->ssid_len == ssid_len) {
            char ap_ssid[33];
            int i;
            for (i = 0; i < ssid_len; i++) ap_ssid[i] = (char)payload[1 + i];
            ap_ssid[ssid_len] = '\0';
            match = (sim_strncasecmp(c->ssid, ap_ssid, ssid_len) == 0);
        }
        if (!match) break;
        if (!sim_cfg_chan_in_list(freq) || bw != c->bss_bw) break;
        (void)enc;

        S.last_peer_ts = g_tick_ms;
        if (S.conn == SIM_CONN_IDLE || S.conn == SIM_CONN_DISCONNECTED) {
            S.conn = SIM_CONN_SCANNING;
        }
        if (S.conn == SIM_CONN_SCANNING) {
            S.conn = SIM_CONN_ASSOCIATING;
            S.next_retry = g_tick_ms + 20;
        }
        /* remember for BSSLIST */
        {
            char ap_ssid[33];
            int i;
            for (i = 0; i < ssid_len; i++) ap_ssid[i] = (char)payload[1 + i];
            ap_ssid[ssid_len] = '\0';
            sim_strlcpy(S.ap_ssid, ap_ssid, sizeof(S.ap_ssid));
            S.ap_freq = freq;
            S.ap_bw = bw;
            S.ap_rssi = (int8_t)(0 - c->rssi);
            S.has_ap = 1;
        }
        break;
    }
    case SIM_LINK_TYPE_ASSOC_RESP: {
        /* payload: status(0=ok) + rssi */
        if (c->mode != SIM_MODE_STA && c->mode != SIM_MODE_APSTA) break;
        if (len < 2 || payload[0] != 0) break;
        if (S.conn != SIM_CONN_CONNECTED) emit("+CONNECTED");   /* 去重 */
        S.conn = SIM_CONN_CONNECTED;
        S.last_peer_ts = g_tick_ms;
        break;
    }
    case SIM_LINK_TYPE_ASSOC_REQ: {
        /* payload: ssid_len, ssid.., mac[6] */
        uint8_t ssid_len;
        int i;
        if (c->mode != SIM_MODE_AP && c->mode != SIM_MODE_APSTA) break;
        if (len < 7) break;
        ssid_len = payload[0];
        if (len < (uint16_t)(1 + ssid_len + 6)) break;
        /* accept if AP has no ssid, or request ssid empty (pairing), or match */
        {
            char req_ssid[33];
            int i;
            int ok;
            for (i = 0; i < ssid_len && i < 32; i++) req_ssid[i] = (char)payload[1 + i];
            req_ssid[i] = '\0';
            ok = (c->ssid_len == 0) || (ssid_len == 0) ||
                 (ssid_len == c->ssid_len &&
                  sim_strncasecmp(req_ssid, c->ssid, ssid_len) == 0);
            if (!ok) break;
        }
        /* pairing: STA sends empty SSID -> push SSID(+PSK) to it */
        if (ssid_len == 0 && S.pairing && c->ssid_len > 0) {
            uint8_t pk[1 + SIM_SSID_MAX + 1 + 64];
            uint8_t m = 0;
            int j, psk_len = sim_strlen(c->psk);
            pk[m++] = (uint8_t)c->ssid_len;
            for (j = 0; j < c->ssid_len; j++) pk[m++] = (uint8_t)c->ssid[j];
            pk[m++] = (uint8_t)psk_len;
            for (j = 0; j < psk_len && j < 64; j++) pk[m++] = (uint8_t)c->psk[j];
            sim_link_send(SIM_LINK_TYPE_PAIR_PSK, pk, m);
        }
        /* add/refresh STA */
        for (i = 0; i < S.sta_cnt; i++) {
            if (sim_memcmp(S.sta_mac[i], &payload[1 + ssid_len], 6) == 0) break;
        }
        if (i >= S.sta_cnt && S.sta_cnt < SIM_MAX_STA) {
            int j;
            for (j = 0; j < 6; j++) S.sta_mac[S.sta_cnt][j] = payload[1 + ssid_len + j];
            S.sta_rssi[S.sta_cnt] = (int8_t)(0 - c->rssi);   /* peer rssi */
            S.sta_cnt++;
            emit("+STA_CONNECTED");
        }
        S.conn = SIM_CONN_CONNECTED;
        S.last_peer_ts = g_tick_ms;
        /* reply assoc resp with our rssi */
        {
            uint8_t resp[2];
            resp[0] = 0;
            resp[1] = (uint8_t)(0 - c->rssi);
            sim_link_send(SIM_LINK_TYPE_ASSOC_RESP, resp, sizeof(resp));
        }
        break;
    }
    case SIM_LINK_TYPE_PAIR_PSK: {
        /* payload: ssid_len, ssid.., psk_len, psk.. */
        uint8_t ssid_len, psk_len;
        if (len < 3) break;
        ssid_len = payload[0];
        if ((uint16_t)(1 + ssid_len) + 1 > len) break;
        psk_len = payload[1 + ssid_len];
        if ((uint16_t)(1 + ssid_len + 1 + psk_len) > len) break;
        if (sim_cfg_get()->ssid_len == 0) {
            char buf[33];
            int i;
            for (i = 0; i < ssid_len && i < 32; i++) buf[i] = (char)payload[1 + i];
            buf[i] = '\0';
            sim_cfg_set_ssid(buf);
        }
        if (psk_len > 0) {
            char psk[65];
            int i;
            for (i = 0; i < psk_len && i < 64; i++) psk[i] = (char)payload[1 + ssid_len + 1 + i];
            psk[psk_len] = '\0';
            sim_cfg_set_psk(psk);
            sim_cfg_mutable()->keymgmt = SIM_KEY_WPA_PSK;
        }
        emit("+PAIR SUCCESS");
        break;
    }
    case SIM_LINK_TYPE_DEAUTH:
        if (S.conn == SIM_CONN_CONNECTED) {
            S.conn = SIM_CONN_DISCONNECTED;
            emit("+DISCONNECTED");
        }
        break;
    case SIM_LINK_TYPE_DATA: {
        /* payload = full ethernet frame; forward if addressed to us */
        uint8_t dst[6];
        int i;
        if (len < 14) break;
        for (i = 0; i < 6; i++) dst[i] = payload[i];
        if (!(mac_is_bcast(dst) || mac_is_me(dst) || mac_is_group(dst))) break;
        if (s_rx_cnt < SIM_RX_QUEUE && len <= SIM_MAX_FRAME) {
            int j;
            for (j = 0; j < len; j++) s_rx_data[s_rx_tail][j] = payload[j];
            s_rx_len[s_rx_tail] = len;
            s_rx_tail = (uint8_t)((s_rx_tail + 1) % SIM_RX_QUEUE);
            s_rx_cnt++;
            S.rx_pkts++;
            spi_slave_notify();    /* IRQ: host has data to read */
        }
        break;
    }
    default:
        break;
    }
}

/* ------------------------------------------------------------------ */
/* main poll (call every ~5 ms)                                       */
/* ------------------------------------------------------------------ */
void sim_wifi_poll(void)
{
    const struct sim_cfg *c = sim_cfg_get();

    /* AP / APSTA: broadcast beacon periodically */
    if (c->mode == SIM_MODE_AP || c->mode == SIM_MODE_APSTA) {
        if ((int32_t)(g_tick_ms - S.next_beacon) >= 0) {
            uint8_t b[3 + SIM_SSID_MAX + 3];
            uint8_t n = 0;
            int i;
            b[n++] = (uint8_t)c->ssid_len;
            for (i = 0; i < c->ssid_len; i++) b[n++] = (uint8_t)c->ssid[i];
            b[n++] = (uint8_t)(c->chan_list[0] >> 8);
            b[n++] = (uint8_t)(c->chan_list[0] & 0xFF);
            b[n++] = c->bss_bw;
            b[n++] = c->keymgmt;
            sim_link_send(SIM_LINK_TYPE_BEACON, b, n);
            S.next_beacon = g_tick_ms + 500;
        }
        /* drop silent STAs (keepalive refreshes within 2s) */
        if (S.sta_cnt > 0 && (int32_t)(g_tick_ms - S.last_peer_ts) > 8000) {
            S.sta_cnt = 0;
            S.conn = SIM_CONN_IDLE;
            emit("+STA_DISCONNECTED");
        }
    }

    /* STA / APSTA: retry association while in ASSOCIATING */
    if ((c->mode == SIM_MODE_STA || c->mode == SIM_MODE_APSTA) &&
        S.conn == SIM_CONN_ASSOCIATING) {
        if ((int32_t)(g_tick_ms - S.next_retry) >= 0) {
            uint8_t req[1 + SIM_SSID_MAX + 6];
            uint8_t n = 0;
            int i;
            req[n++] = (uint8_t)c->ssid_len;
            for (i = 0; i < c->ssid_len; i++) req[n++] = (uint8_t)c->ssid[i];
            for (i = 0; i < 6; i++) req[n++] = c->mac[i];
            sim_link_send(SIM_LINK_TYPE_ASSOC_REQ, req, n);
            S.next_retry = g_tick_ms + 500;
        }
    }

    /* STA: if we lost the AP (no beacon for a while) -> disconnected */
    if ((c->mode == SIM_MODE_STA || c->mode == SIM_MODE_APSTA) &&
        S.conn == SIM_CONN_CONNECTED) {
        if ((int32_t)(g_tick_ms - S.last_peer_ts) > 3000) {
            S.conn = SIM_CONN_DISCONNECTED;
            emit("+DISCONNECTED");
        }
        /* keepalive: periodically refresh the AP's STA entry so it is not
         * dropped as "silent"; ASSOC_RESP handler de-duplicates events */
        if ((int32_t)(g_tick_ms - S.next_keepalive) >= 0) {
            uint8_t req[1 + SIM_SSID_MAX + 6];
            uint8_t n = 0;
            int i;
            req[n++] = (uint8_t)c->ssid_len;
            for (i = 0; i < c->ssid_len; i++) req[n++] = (uint8_t)c->ssid[i];
            for (i = 0; i < 6; i++) req[n++] = c->mac[i];
            sim_link_send(SIM_LINK_TYPE_ASSOC_REQ, req, n);
            S.next_keepalive = g_tick_ms + 2000;
        }
    }
}

/* ------------------------------------------------------------------ */
/* data path to host                                                  */
/* ------------------------------------------------------------------ */
int sim_wifi_send_data(const uint8_t *frame, uint16_t len)
{
    const struct sim_cfg *c = sim_cfg_get();

    if (len < 14 || len > SIM_MAX_FRAME) return -1;
    if (c->mode == SIM_MODE_STA || c->mode == SIM_MODE_APSTA) {
        if (S.conn != SIM_CONN_CONNECTED) return -1;
    }
    if (c->mode == SIM_MODE_AP && S.sta_cnt == 0) return -1;

    sim_link_send(SIM_LINK_TYPE_DATA, frame, len);
    S.tx_pkts++;
    return 0;
}

int sim_wifi_take_rx(uint8_t *buf, uint16_t *len)
{
    int i;
    if (s_rx_cnt == 0) return -1;
    for (i = 0; i < s_rx_len[s_rx_head]; i++) buf[i] = s_rx_data[s_rx_head][i];
    *len = s_rx_len[s_rx_head];
    s_rx_head = (uint8_t)((s_rx_head + 1) % SIM_RX_QUEUE);
    s_rx_cnt--;
    return 0;
}

int sim_wifi_take_event(char *buf, uint16_t size)
{
    if (s_evt_cnt == 0) return -1;
    sim_strlcpy(buf, s_evt[s_evt_head], size);
    s_evt_head = (uint8_t)((s_evt_head + 1) % SIM_EVT_QUEUE);
    s_evt_cnt--;
    return 0;
}

int sim_wifi_has_rx(void)    { return s_rx_cnt > 0; }
int sim_wifi_has_event(void) { return s_evt_cnt > 0; }

int sim_wifi_last_ap(char *ssid, uint16_t *freq, uint8_t *bw, int8_t *rssi)
{
    if (!S.has_ap) return 0;
    sim_strlcpy(ssid, S.ap_ssid, 33);
    *freq = S.ap_freq;
    *bw = S.ap_bw;
    *rssi = S.ap_rssi;
    return 1;
}

/* ------------------------------------------------------------------ */
void sim_wifi_fill_state(struct sim_state *st)
{
    const struct sim_cfg *c = sim_cfg_get();
    int i;
    st->mode = c->mode;
    st->conn_state = S.conn;
    st->sta_cnt = S.sta_cnt;
    st->rssi = (S.conn == SIM_CONN_CONNECTED) ? c->rssi : (int8_t)0;
    st->pairing = S.pairing;
    st->encrypt = (c->keymgmt == SIM_KEY_WPA_PSK) ? 1 : 0;
    for (i = 0; i < 6; i++) st->mac[i] = c->mac[i];
    st->ssid_len = c->ssid_len;
    for (i = 0; i < c->ssid_len; i++) st->ssid[i] = c->ssid[i];
    st->ssid[32 - 1] = '\0';
    for (i = 0; i < SIM_CHAN_MAX; i++) st->chan_list[i] = c->chan_list[i];
    st->chan_cnt = c->chan_cnt;
    st->bss_bw = c->bss_bw;
    st->up_time_ms = g_tick_ms;
}

void sim_wifi_init(void)
{
    int i;
    S.conn = SIM_CONN_IDLE;
    S.pairing = 0;
    S.scan_busy = 0;
    S.next_beacon = 100;
    S.next_retry = 0;
    S.next_keepalive = 0;
    S.last_peer_ts = 0;
    S.tx_pkts = S.rx_pkts = 0;
    S.sta_cnt = 0;
    S.has_ap = 0;
    s_rx_head = s_rx_tail = s_rx_cnt = 0;
    s_evt_head = s_evt_tail = s_evt_cnt = 0;
    for (i = 0; i < SIM_MAX_STA; i++) S.sta_rssi[i] = 0;
}
