/* uart.c — interrupt-driven USART driver (USART1/2) */
#include "uart.h"
#include "board.h"
#include "gpio.h"

#define UART_MAX_INST 2

static uart_rx_cb s_cb[UART_MAX_INST];
static USART_TypeDef *s_uart[UART_MAX_INST];
static uint8_t s_cnt = 0;

static int uart_index(USART_TypeDef *u)
{
    int i;
    for (i = 0; i < s_cnt; i++) {
        if (s_uart[i] == u) return i;
    }
    return -1;
}

static int sim_strlen(const char *s)
{
    int n = 0;
    while (s && s[n]) n++;
    return n;
}

void uart_init(USART_TypeDef *uart, GPIO_TypeDef *port,
               uint8_t tx_pin, uint8_t rx_pin,
               uint32_t baud, IRQn_Type irqn, uart_rx_cb cb)
{
    int idx = uart_index(uart);

    if (idx < 0 && s_cnt < UART_MAX_INST) {
        idx = s_cnt;
        s_uart[idx] = uart;
        s_cb[idx] = cb;
        s_cnt++;
    }

    /* ★★ 外设时钟**必须先开**：USART1 在 APB2（BIT14），USART2/3 在 APB1（BIT17/18）。
     * 漏了这条 ⇒ USART 寄存器不响应，现象是"串口完全不响"（发不出也收不到），很难查。
     * 放在驱动里而不是 main，是因为**只有这里知道这个 USART 挂在哪条总线上**。
     * （2026-09-21 补：PC 侧模拟器看不出来，一上真板就现形 —— 同 orpah-client-demo 的修法。）*/
    if (uart == USART1)      { RCC->APB2PCENR |= RCC_APB2Periph_USART1; }
    else if (uart == USART2) { RCC->APB1PCENR |= RCC_APB1Periph_USART2; }
    else if (uart == USART3) { RCC->APB1PCENR |= RCC_APB1Periph_USART3; }

    /* TX = AF push-pull, RX = input floating */
    gpio_set_mode(port, tx_pin, GPIO_MODE_AF_PP_50MHZ);
    gpio_set_mode(port, rx_pin, GPIO_MODE_IN_FLOATING);

    /* baud = PCLK / baud; both USARTs on 8 MHz bus */
    uart->BRR = (SYSTEM_CLOCK_HZ + baud / 2) / baud;

    /* UE | RE | TE | RXNEIE */
    uart->CTLR1 = USART_CTLR1_UE | USART_CTLR1_RE | USART_CTLR1_TE |
                  USART_CTLR1_RXNEIE;

    NVIC_EnableIRQ(irqn);
}

void uart_putc(USART_TypeDef *uart, uint8_t c)
{
    while (!(uart->STATR & USART_FLAG_TXE)) { }
    uart->DATAR = c;
}

void uart_write(USART_TypeDef *uart, const uint8_t *data, uint32_t len)
{
    uint32_t i;
    for (i = 0; i < len; i++) {
        uart_putc(uart, data[i]);
    }
}

/* ---------------------------------------------------------------------------
 * uart_printf —— 极小 printf（`-nostdlib` 下没有 libc 的替代品）
 *
 * 支持：`%s` `%d/%i` `%u` `%x/%X` `%c` `%%`，**以及宽度与 0 补位**（`%08x`、`%02x`、`%5u`）。
 *
 * ★ 为什么必须支持宽度（2026-09-22 上机踩坑）：以前只认转换符 ⇒ `%08x` / `%02x` 被**原样打出来**，
 *   而这两处恰恰是排障最需要的诊断输出。现场证据就是 `[id] boot_entropy=0x%08x` 打出了字面量
 *   （软熵 nonce 的熵值读不出来，于是没法用公式离线复现设备那一帧；SE 失败时的 raw 字节也读不出来）。
 * ★ 不认识的写法仍**原样打印**（可见，绝不静默）：不支持 `-` 左对齐 / `+` / 空格 / 精度 ——
 *   用到就会在串口上看见它本身，别指望它生效。
 * ★ 所有写入都走 `EMIT`（**有界**，上限 `sizeof(buf)-1`）：`buf` 在栈上，越界就是当场破坏别的变量。
 *   老实现里 `%d/%u/%x` 的分支在写数字前没有边界检查（`tmp[12]` 最多 11 字符，而 `j` 可能已接近满
 *   ⇒ 可能越界），这里一并收进有界的 EMIT。
 *
 * ⚠ 本文件是**平台层两份独立副本**之一（另一份 = `halow-demo/simulator/firmware/Periph/uart.c`）：
 *   改这一侧就要把同一份改动同步到另一侧（本仓这套**已上机**，参考仓那套**未上机**）。
 * -------------------------------------------------------------------------*/
void uart_printf(USART_TypeDef *uart, const char *fmt, ...)
{
    char buf[128];
    va_list ap;
    int n;

/* ★ EMIT 必须**无条件求值**它的参数（2026-09-22 宿主对拍当场抓到的真坑）：
 *   写成 `if (j < …) { buf[j++] = (char)(ch); }` 时，参数一旦带副作用
 *   （`*s++` / `tmp[--k]` / `va_arg(...)`），缓冲满之后参数**就不再被求值** ⇒
 *   `s` / `k` 不再前进 ⇒ `while (*s)` / `while (k > 0)` **死循环**
 *   （实测：`uart_printf(0, "%s", 399 字符)` 当场卡住），
 *   而 `va_arg` 不被消费还会让**后续参数整体错位**。先求值、再判断写不写。*/
#define EMIT(ch) do { char emit_c_ = (char)(ch); \
                      if (j < (int)sizeof(buf) - 1) { buf[j++] = emit_c_; } } while (0)

    va_start(ap, fmt);
    n = 0;
    {
        /* minimal vsnprintf replacement (no libc on some toolchains) */
        const char *p = fmt;
        int j = 0;
        while (*p && j < (int)sizeof(buf) - 1) {
            const char *spec;
            int zero, width, pad;

            if (*p != '%') {
                EMIT(*p);
                p++;
                continue;
            }
            spec = p;                   /* 指向 '%'：不认识的写法要整段原样打印 */
            p++;
            zero = 0;
            width = 0;
            if (*p == '0') { zero = 1; p++; }                            /* 补零标志 */
            while (*p >= '0' && *p <= '9') { width = width * 10 + (int)(*p - '0'); p++; }
            if (width > (int)sizeof(buf) - 1) { width = (int)sizeof(buf) - 1; }

            if (*p == 's') {
                const char *s = va_arg(ap, const char *);
                int len = 0;
                if (!s) s = "(null)";
                while (s[len]) len++;
                for (pad = width - len; pad > 0; pad--) { EMIT(' '); }
                while (*s) { EMIT(*s++); }
            } else if (*p == 'd' || *p == 'i' || *p == 'u' || *p == 'x' || *p == 'X') {
                char tmp[24];
                int k = 0;
                int neg = 0;
                unsigned int u;
                if (*p == 'd' || *p == 'i') {
                    int v = va_arg(ap, int);
                    neg = (v < 0);
                    /* ⚠ INT_MIN 直接取负会溢出 ⇒ 先 +1 再取负 */
                    u = neg ? ((unsigned int)(-(v + 1)) + 1u) : (unsigned int)v;
                } else {
                    u = va_arg(ap, unsigned int);
                }
                if (*p == 'x' || *p == 'X') {
                    const char *hex = (*p == 'x') ? "0123456789abcdef" : "0123456789ABCDEF";
                    do { tmp[k++] = hex[u & 0xFu]; u >>= 4; } while (u != 0u);
                } else {
                    do { tmp[k++] = (char)('0' + (int)(u % 10u)); u /= 10u; } while (u != 0u);
                }
                if (neg) { EMIT('-'); }
                for (pad = width - k - (neg ? 1 : 0); pad > 0; pad--) { EMIT(zero ? '0' : ' '); }
                while (k > 0) { EMIT(tmp[--k]); }
            } else if (*p == 'c') {
                for (pad = width - 1; pad > 0; pad--) { EMIT(' '); }
                EMIT((char)va_arg(ap, int));
            } else if (*p == '%') {
                EMIT('%');
            } else {
                const char *q;          /* 不认识：整段原样打印（可见，不静默）*/
                for (q = spec; q <= p && *q; q++) { EMIT(*q); }
            }
            /* ★ 只有真读到转换符才前进：格式串以单个 '%' 结尾时 `*p == 0`，
             *   无条件 `p++` 会越过字符串末尾继续读（老实现就有这个洞 ——
             *   2026-09-22 宿主对拍用例 `"100%"` 当场把它复现成卡死）。*/
            if (*p != '\0') { p++; }
        }
        buf[j] = '\0';
        n = j;
    }
    va_end(ap);
    (void)n;
    uart_write(uart, (const uint8_t *)buf, (uint32_t)sim_strlen(buf));

#undef EMIT
}

void uart_irq_rx(USART_TypeDef *uart)
{
    int idx = uart_index(uart);
    uint8_t b;

    while (uart->STATR & USART_FLAG_RXNE) {
        b = (uint8_t)(uart->DATAR & 0xFF);
        if (idx >= 0 && s_cb[idx]) {
            s_cb[idx](b);
        }
    }
}
