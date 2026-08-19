/* sim_at.c — AT command engine
 *
 * Command/response conventions follow the TXW8301 libatcmd layer:
 *   - case-insensitive, newline mode
 *   - query  : AT+XXX?
 *   - set    : AT+XXX=value
 *   - success: OK\r\n    error: ERROR\r\n    value: XXX:value\r\nOK\r\n
 *   - async events are +XXX lines (emitted by sim_wifi)
 */
#include "sim_at.h"
#include "sim_util.h"
#include "sim_cfg.h"
#include "sim_wifi.h"
#include "sim_link.h"
#include "board.h"
#include "uart.h"

/* ------------------------------------------------------------------ */
/* capture buffer (for SPI AT_CMD responses)                          */
/* ------------------------------------------------------------------ */
static char *s_cap;
static int   s_cap_len, s_cap_size, s_cap_active;

/* debug flags */
static int s_dbg_lmac, s_dbg_wnb;

int sim_at_dbg_lmac(void) { return s_dbg_lmac; }
int sim_at_dbg_wnb(void)  { return s_dbg_wnb; }

/* ------------------------------------------------------------------ */
/* output helpers                                                     */
/* ------------------------------------------------------------------ */
static void cap_puts(const char *s)
{
    while (*s) {
        if (s_cap_active && s_cap_len < s_cap_size - 1) s_cap[s_cap_len++] = *s;
        s++;
    }
    if (s_cap_active) s_cap[s_cap_len] = '\0';
}

static void at_printf(const char *fmt, ...)
{
    char tmp[160];
    va_list ap;
    int j = 0;
    const char *p = fmt;

    va_start(ap, fmt);
    for (; *p && j < (int)sizeof(tmp) - 1; p++) {
        if (*p == '%') {
            p++;
            if (*p == 's') {
                const char *s = va_arg(ap, const char *);
                if (!s) s = "(null)";
                while (*s && j < (int)sizeof(tmp) - 1) tmp[j++] = *s++;
            } else if (*p == 'd' || *p == 'i') {
                int v = va_arg(ap, int);
                char tb[12];
                int k = 0;
                unsigned int u = (v < 0) ? (unsigned int)(-v) : (unsigned int)v;
                if (v < 0) tb[k++] = '-';
                do { tb[k++] = (char)('0' + u % 10); u /= 10; } while (u);
                while (k > 0) tmp[j++] = tb[--k];
            } else if (*p == 'u') {
                unsigned int u = va_arg(ap, unsigned int);
                char tb[12];
                int k = 0;
                do { tb[k++] = (char)('0' + u % 10); u /= 10; } while (u);
                while (k > 0) tmp[j++] = tb[--k];
            } else if (*p == 'x' || *p == 'X') {
                unsigned int u = va_arg(ap, unsigned int);
                char tb[12];
                int k = 0;
                const char *hx = "0123456789abcdef";
                do { tb[k++] = hx[u & 0xF]; u >>= 4; } while (u);
                while (k > 0) tmp[j++] = tb[--k];
            } else if (*p == 'c') {
                tmp[j++] = (char)va_arg(ap, int);
            } else if (*p == '%') {
                tmp[j++] = '%';
            } else {
                tmp[j++] = '%';
                tmp[j++] = *p;
            }
        } else {
            tmp[j++] = *p;
        }
    }
    tmp[j] = '\0';
    va_end(ap);

    uart_printf(CONSOLE_UART, "%s", tmp);
    cap_puts(tmp);
}

#define at_ok()      at_printf("OK\r\n")
#define at_error()   at_printf("ERROR\r\n")
#define at_query()   (args != 0 && args[0] == '?')

/* ------------------------------------------------------------------ */
/* handlers: return 0 if handled                                      */
/* ------------------------------------------------------------------ */
static int hdl_mode(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (at_query()) {
        at_printf("MODE:%s\r\n", (c->mode == SIM_MODE_AP) ? "AP" :
                  (c->mode == SIM_MODE_STA) ? "STA" :
                  (c->mode == SIM_MODE_APSTA) ? "APSTA" : "GROUP");
        at_ok();
        return 0;
    }
    if (sim_strcasecmp(args, "AP") == 0) sim_cfg_set_mode(SIM_MODE_AP);
    else if (sim_strcasecmp(args, "STA") == 0) sim_cfg_set_mode(SIM_MODE_STA);
    else if (sim_strcasecmp(args, "APSTA") == 0) sim_cfg_set_mode(SIM_MODE_APSTA);
    else if (sim_strcasecmp(args, "GROUP") == 0) sim_cfg_set_mode(SIM_MODE_GROUP);
    else { at_error(); return 0; }
    sim_wifi_init();
    at_ok();
    return 0;
}

static int hdl_ssid(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (at_query()) {
        at_printf("SSID:%s\r\n", c->ssid);
        at_ok();
        return 0;
    }
    if (sim_cfg_set_ssid(args) != 0) { at_error(); return 0; }
    at_ok();
    return 0;
}

static int hdl_keymgmt(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (at_query()) {
        at_printf("KEYMGMT:%s\r\n", (c->keymgmt == SIM_KEY_WPA_PSK) ? "WPA-PSK" : "NONE");
        at_ok();
        return 0;
    }
    if (sim_strcasecmp(args, "WPA-PSK") == 0) {
        sim_cfg_mutable()->keymgmt = SIM_KEY_WPA_PSK;
        at_ok();
    } else if (sim_strcasecmp(args, "NONE") == 0) {
        sim_cfg_mutable()->keymgmt = SIM_KEY_NONE;
        at_ok();
    } else {
        at_error();
    }
    return 0;
}

static int hdl_psk(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (at_query()) {
        at_printf("PSK:%s\r\n", c->psk);
        at_ok();
        return 0;
    }
    if (sim_cfg_set_psk(args) != 0) { at_error(); return 0; }
    at_ok();
    return 0;
}

static int hdl_pair(const char *args)
{
    int v = sim_atoi(args);
    if (v == 1) { sim_wifi_set_pairing(1); at_ok(); }
    else if (v == 0) {
        sim_wifi_set_pairing(0);
        at_printf("PAIR STOP\r\n");
        at_ok();
    } else {
        at_error();
    }
    return 0;
}

static int hdl_bss_bw(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("BSS_BW:%d\r\n", (int)c->bss_bw); at_ok(); return 0; }
    v = sim_atoi(args);
    if (v != 1 && v != 2 && v != 4 && v != 8) { at_error(); return 0; }
    sim_cfg_mutable()->bss_bw = (uint8_t)v;
    at_ok();
    return 0;
}

static int hdl_freq_range(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    char *s, *e;
    int start, end, step, i, n;
    uint16_t list[SIM_CHAN_MAX];

    if (at_query()) {
        at_printf("FREQ_RANGE:%d,%d\r\n",
                  (int)c->chan_list[0],
                  (int)c->chan_list[c->chan_cnt > 0 ? c->chan_cnt - 1 : 0]);
        at_ok();
        return 0;
    }
    s = (char *)args;
    e = sim_token(s, ',');
    if (!e) { at_error(); return 0; }
    start = sim_atoi(s);
    end   = sim_atoi(e);
    if (start <= 0 || end < start) { at_error(); return 0; }
    step = (int)c->bss_bw * 10;   /* 0.1MHz unit */
    n = 0;
    for (i = start; i <= end && n < SIM_CHAN_MAX; i += step) {
        list[n++] = (uint16_t)i;
    }
    if (n == 0) { at_error(); return 0; }
    sim_cfg_set_chan_list(list, n);
    at_ok();
    return 0;
}

static int hdl_chan_list(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    char *p, *nxt;
    uint16_t list[SIM_CHAN_MAX];
    int n = 0, i;

    if (at_query()) {
        at_printf("CHAN_LIST:");
        for (i = 0; i < c->chan_cnt; i++) {
            at_printf("%s%d", i ? "," : "", (int)c->chan_list[i]);
        }
        at_printf("\r\n");
        at_ok();
        return 0;
    }
    p = (char *)args;
    while (p && n < SIM_CHAN_MAX) {
        nxt = sim_token(p, ',');
        list[n++] = (uint16_t)sim_atoi(p);
        p = nxt;
    }
    if (n == 0 || sim_cfg_set_chan_list(list, n) != 0) { at_error(); return 0; }
    at_ok();
    return 0;
}

static int hdl_rssi(const char *args)
{
    int idx = 0;
    int v;
    if (at_query() || args == 0 || args[0] == '\0') idx = 0;
    else idx = sim_atoi(args);
    if (idx > 0) idx -= 1;
    v = sim_wifi_get_rssi(idx);
    at_printf("RSSI:%d\r\n", v);
    at_ok();
    return 0;
}

static int hdl_conn_state(const char *args)
{
    (void)args;
    at_printf("CONN_STATE:%s\r\n", sim_wifi_conn_str());
    at_ok();
    return 0;
}

static int hdl_wnbcfg(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int i;
    (void)args;
    at_printf("WIFI MODE:%d\r\n", (int)c->mode);
    at_printf("SSID:%s\r\n", c->ssid);
    at_printf("BSS_BW:%d\r\n", (int)c->bss_bw);
    at_printf("CHAN_LIST:");
    for (i = 0; i < c->chan_cnt; i++) at_printf("%s%d", i ? "," : "", (int)c->chan_list[i]);
    at_printf("\r\n");
    at_printf("KEYMGMT:%s\r\n", (c->keymgmt == SIM_KEY_WPA_PSK) ? "WPA-PSK" : "NONE");
    at_printf("TXPOWER:%d\r\n", (int)c->txpower);
    at_printf("TX_MCS:%d\r\n", (int)c->tx_mcs);
    at_printf("HEART_INT:%d\r\n", (int)c->heart_int);
    at_printf("ACKTMO:%d\r\n", (int)c->ack_tmo);
    at_printf("ROAM:%d\r\n", (int)c->roam);
    at_printf("CONN_STATE:%s\r\n", sim_wifi_conn_str());
    at_printf("RSSI:%d\r\n", sim_wifi_get_rssi(0));
    at_printf("MAC_ADDR:");
    for (i = 0; i < 6; i++) at_printf("%s%02x", i ? ":" : "", (int)c->mac[i]);
    at_printf("\r\n");
    at_ok();
    return 0;
}

static int hdl_scan_ap(const char *args)
{
    int secs = sim_atoi(args);
    if (secs <= 0 || secs > 30) secs = 2;
    /* In a real device this scans; here the STA already hears beacons.
     * Mark a scan window and return OK. */
    at_printf("SCAN START %ds\r\n", secs);
    at_ok();
    return 0;
}

static int hdl_bsslist(const char *args)
{
    char ssid[33];
    uint16_t freq;
    uint8_t bw;
    int8_t rssi;
    (void)args;
    if (sim_wifi_last_ap(ssid, &freq, &bw, &rssi)) {
        at_printf("BSS:SSID=%s,FREQ=%d,BW=%d,RSSI=%d\r\n", ssid, (int)freq, (int)bw, (int)rssi);
    } else {
        at_printf("BSSLIST:0\r\n");
    }
    at_ok();
    return 0;
}

static int hdl_mac_addr(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    uint8_t mac[6];
    int i;
    if (at_query()) {
        at_printf("MAC_ADDR:");
        for (i = 0; i < 6; i++) at_printf("%s%02x", i ? ":" : "", (int)c->mac[i]);
        at_printf("\r\n");
        at_ok();
        return 0;
    }
    /* optional set: xx:xx:xx:xx:xx:xx */
    {
        int n = sim_hex_to_bytes(args, mac, 6);
        if (n == 6) {
            for (i = 0; i < 6; i++) sim_cfg_mutable()->mac[i] = mac[i];
            at_ok();
            return 0;
        }
    }
    at_error();
    return 0;
}

static int hdl_version(const char *args)
{
    (void)args;
    at_printf("VERSION:%s\r\n", SIM_VERSION_STR);
    at_ok();
    return 0;
}

static int hdl_txpower(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("TXPOWER:%d\r\n", (int)c->txpower); at_ok(); return 0; }
    v = sim_atoi(args);
    if (v < 6 || v > 20) { at_error(); return 0; }
    sim_cfg_mutable()->txpower = (uint8_t)v;
    at_ok();
    return 0;
}

static int hdl_ack_tmo(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    if (at_query()) { at_printf("ACKTMO:%d\r\n", (int)c->ack_tmo); at_ok(); return 0; }
    sim_cfg_mutable()->ack_tmo = (uint16_t)sim_atoi(args);
    at_ok();
    return 0;
}

static int hdl_tx_mcs(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("TX_MCS:%d\r\n", (int)c->tx_mcs); at_ok(); return 0; }
    v = sim_atoi(args);
    if ((v < 0 || v > 7) && v != 255) { at_error(); return 0; }
    sim_cfg_mutable()->tx_mcs = (uint8_t)v;
    at_ok();
    return 0;
}

static int hdl_heart_int(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("HEART_INT:%d\r\n", (int)c->heart_int); at_ok(); return 0; }
    v = sim_atoi(args);
    if (v < 1 || v > 60000) { at_error(); return 0; }
    sim_cfg_mutable()->heart_int = (uint16_t)v;
    at_ok();
    return 0;
}

static int hdl_roam(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("ROAM:%d\r\n", (int)c->roam); at_ok(); return 0; }
    v = sim_atoi(args);
    if (v != 0 && v != 1) { at_error(); return 0; }
    sim_cfg_mutable()->roam = (uint8_t)v;
    at_ok();
    return 0;
}

static int hdl_joingroup(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    char *macs, *aidstr;
    uint8_t mac[6];
    int n;
    if (c->mode != SIM_MODE_GROUP) { at_error(); return 0; }
    macs = (char *)args;
    aidstr = sim_token(macs, ',');
    if (!aidstr) { at_error(); return 0; }
    n = sim_hex_to_bytes(macs, mac, 6);
    if (n != 6) { at_error(); return 0; }
    {
        int i;
        for (i = 0; i < 6; i++) sim_cfg_mutable()->group[i] = mac[i];
    }
    sim_cfg_mutable()->aid = (uint8_t)sim_atoi(aidstr);
    at_ok();
    return 0;
}

static int hdl_ps_mode(const char *args)
{
    const struct sim_cfg *c = sim_cfg_get();
    int v;
    if (at_query()) { at_printf("PS_MODE:%d\r\n", (int)c->ps_mode); at_ok(); return 0; }
    v = sim_atoi(args);
    if (v < 0 || v > 4) { at_error(); return 0; }
    sim_cfg_mutable()->ps_mode = (uint8_t)v;
    at_ok();
    return 0;
}

static int hdl_r_ssid(const char *args)
{
    struct sim_cfg *c = sim_cfg_mutable();
    if (at_query()) { at_printf("R_SSID:%s\r\n", c->r_ssid); at_ok(); return 0; }
    if (sim_strlen(args) == 0 || sim_strlen(args) > SIM_SSID_MAX) { at_error(); return 0; }
    sim_strlcpy(c->r_ssid, args, SIM_SSID_MAX + 1);
    c->r_ssid_len = (uint8_t)sim_strlen(args);
    at_ok();
    return 0;
}

static int hdl_r_psk(const char *args)
{
    struct sim_cfg *c = sim_cfg_mutable();
    if (at_query()) { at_printf("R_PSK:%s\r\n", c->r_psk); at_ok(); return 0; }
    if (sim_strlen(args) != 64) { at_error(); return 0; }
    sim_strlcpy(c->r_psk, args, 65);
    at_ok();
    return 0;
}

static int hdl_loaddef(const char *args)
{
    if (sim_atoi(args) != 1) { at_error(); return 0; }
    at_printf("RESTORE FACTORY\r\n");
    sim_cfg_reset();
    sim_wifi_init();
    NVIC_SystemReset();
    return 0;
}

static int hdl_sysdbg(const char *args)
{
    char *which, *val;
    int v;
    if (at_query()) {
        at_printf("SYSDBG:LMAC=%d,WNB=%d\r\n", s_dbg_lmac, s_dbg_wnb);
        at_ok();
        return 0;
    }
    which = (char *)args;
    val = sim_token(which, ',');
    if (!val) { at_error(); return 0; }
    v = sim_atoi(val);
    if (sim_strcasecmp(which, "lmac") == 0) s_dbg_lmac = v ? 1 : 0;
    else if (sim_strcasecmp(which, "wnb") == 0) s_dbg_wnb = v ? 1 : 0;
    else { at_error(); return 0; }
    at_ok();
    return 0;
}

static int hdl_txdata(const char *args)
{
    int len;
    if (at_query()) { at_error(); return 0; }
    len = sim_atoi(args);
    if (len < 14 || len > SIM_MAX_FRAME) { at_error(); return 0; }
    at_printf("OK\r\n");
    sim_at_begin_txdata((uint16_t)len);
    return 0;
}

static int hdl_rst(const char *args)
{
    (void)args;
    NVIC_SystemReset();
    return 0;
}

/* ------------------------------------------------------------------ */
/* command table                                                      */
/* ------------------------------------------------------------------ */
struct at_cmd {
    const char *name;                 /* e.g. "AT+MODE" */
    int (*hdl)(const char *args);
};

static const struct at_cmd s_cmds[] = {
    { "AT+MODE",       hdl_mode },
    { "AT+SSID",       hdl_ssid },
    { "AT+KEYMGMT",    hdl_keymgmt },
    { "AT+PSK",        hdl_psk },
    { "AT+PAIR",       hdl_pair },
    { "AT+BSS_BW",     hdl_bss_bw },
    { "AT+FREQ_RANGE", hdl_freq_range },
    { "AT+CHAN_LIST",  hdl_chan_list },
    { "AT+RSSI",       hdl_rssi },
    { "AT+CONN_STATE", hdl_conn_state },
    { "AT+WNBCFG",     hdl_wnbcfg },
    { "AT+SCAN_AP",    hdl_scan_ap },
    { "AT+BSSLIST",    hdl_bsslist },
    { "AT+MAC_ADDR",   hdl_mac_addr },
    { "AT+VERSION",    hdl_version },
    { "AT+TXPOWER",    hdl_txpower },
    { "AT+ACKTMO",     hdl_ack_tmo },
    { "AT+ACK_TO",     hdl_ack_tmo },
    { "AT+TX_MCS",     hdl_tx_mcs },
    { "AT+HEART_INT",  hdl_heart_int },
    { "AT+ROAM",       hdl_roam },
    { "AT+JOINGROUP",  hdl_joingroup },
    { "AT+PS_MODE",    hdl_ps_mode },
    { "AT+R_SSID",     hdl_r_ssid },
    { "AT+R_PSK",      hdl_r_psk },
    { "AT+LOADDEF",    hdl_loaddef },
    { "AT+SYSDBG",     hdl_sysdbg },
    { "AT+TXDATA",     hdl_txdata },
    { "AT+RST",        hdl_rst },
};

#define AT_CMD_CNT ((int)(sizeof(s_cmds) / sizeof(s_cmds[0])))

/* ------------------------------------------------------------------ */
/* data-mode (AT+TXDATA raw frame)                                    */
/* ------------------------------------------------------------------ */
static uint8_t s_txdata_buf[SIM_MAX_FRAME];
static uint16_t s_txdata_len, s_txdata_idx;
static uint8_t  s_txdata_active;

void sim_at_begin_txdata(uint16_t len)
{
    s_txdata_len = len;
    s_txdata_idx = 0;
    s_txdata_active = 1;
}

int sim_at_txdata_active(void) { return s_txdata_active; }

int sim_at_data_byte(uint8_t b)
{
    if (!s_txdata_active) return 0;
    if (s_txdata_idx < s_txdata_len) {
        s_txdata_buf[s_txdata_idx++] = b;
    }
    if (s_txdata_idx >= s_txdata_len) {
        s_txdata_active = 0;
        if (sim_wifi_send_data(s_txdata_buf, s_txdata_len) == 0) {
            uart_printf(CONSOLE_UART, "TX DATA OK\r\n");
        } else {
            uart_printf(CONSOLE_UART, "TX DATA FAIL\r\n");
        }
        return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* entry point                                                        */
/* ------------------------------------------------------------------ */
int sim_at_run(const char *line, char *resp, int resp_size)
{
    char cmd[80];
    char *args;
    int n, i;

    /* set capture */
    if (resp && resp_size > 0) {
        s_cap = resp;
        s_cap_size = resp_size;
        s_cap_len = 0;
        s_cap[0] = '\0';
        s_cap_active = 1;
    } else {
        s_cap_active = 0;
    }

    /* "AT" alone -> OK */
    if (sim_strcasecmp(line, "AT") == 0) { at_ok(); goto out; }

    if (sim_strncasecmp(line, "AT+", 3) != 0) {
        at_error();
        goto out;
    }

    /* split CMD / args at '=' or query '?' */
    n = 0;
    while (line[3 + n] && line[3 + n] != '=' && line[3 + n] != '?' &&
           n < (int)sizeof(cmd) - 1) {
        cmd[n] = line[3 + n];
        n++;
    }
    cmd[n] = '\0';
    if (line[3 + n] == '=') args = (char *)&line[3 + n + 1];
    else if (line[3 + n] == '?') args = (char *)"?";
    else args = (char *)"";   /* never NULL: handlers rely on non-NULL */

    /* lookup case-insensitive */
    for (i = 0; i < AT_CMD_CNT; i++) {
        if (sim_strcasecmp(cmd, s_cmds[i].name + 3) == 0) {
            s_cmds[i].hdl(args);
            goto out;
        }
    }

    at_error();

out:
    if (s_cap_active) s_cap[s_cap_len] = '\0';
    return 0;
}
