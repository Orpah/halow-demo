/* spi_proto.h — SPI 宿主接口的**协议层**（帧组装 / CRC / 应答构造），与寄存器、中断无关。
 *
 * 单一源：`docs/spi_protocol.md` §2（帧格式）/ §3（命令字）。
 *
 *  偏移 0   CMD      1 字节（bit7=1 表示应答）
 *  偏移 1   LEN_H    1
 *  偏移 2   LEN_L    1
 *  偏移 3   CRC      1 = CRC-8/ATM(poly 0x07, init 0x00) over CMD..LEN_L + 全部载荷
 *  偏移 4.. PAYLOAD  LEN
 *
 * ★ 为什么单独拆一层（2026-09-22）：SPI 从机的**寄存器/EXTI 部分只能上机验**，
 *   而帧协议层是纯逻辑 ⇒ 可以**离线对拍**。现在：
 *     · 设备侧 = 本文件（`firmware/Simulator/spi_proto.c`，编进固件）
 *     · 主机侧 = `tools/spi_frame.py`（Python，同时也喂 sim_config 的 CH341A 传输）
 *     · 两边跑同一批向量逐字节比：`python tools/check_spi_proto.py`（退出码 0 = 一致）
 *   这样"帧格式写错"这类问题在上机前就能被发现，而不是表现为"发出去没反应"。
 *
 * ⚠ 本层**不含**：SPI 寄存器初始化、中断入口、CS(EXTI) 边沿检测、IRQ 输出线、
 *   命令的业务处理（那是 `Periph/spi_slave.c` 的事）。
 * ⚠ **不改协议**：只是把原来写在一个文件里的帧逻辑搬到这一层，字节行为逐位保持
 *   （`docs/spi_protocol.md` 不动）。
 */
#ifndef __SPI_PROTO_H__
#define __SPI_PROTO_H__

#include <stddef.h>
#include <stdint.h>

#define SPI_PROTO_HDR        4
#define SPI_PROTO_RESP_FLAG  0x80
#define SPI_PROTO_MAX_FRAME  1700        /* = MACBUS DATA_AREA_SIZE（含以太网头）*/

/* 命令字（§3）。应答头 = CMD|RESP_FLAG。 */
#define SPI_PROTO_CMD_AT        0x01
#define SPI_PROTO_CMD_GET_STATE 0x02
#define SPI_PROTO_CMD_DATA_TX   0x03
#define SPI_PROTO_CMD_DATA_RX   0x04
#define SPI_PROTO_CMD_EVENT     0x05
#define SPI_PROTO_CMD_PING      0x06
#define SPI_PROTO_CMD_RESET     0x07
#define SPI_PROTO_CMD_SET_CFG   0x08
#define SPI_PROTO_CMD_GET_CFG   0x09

/* 逐字节接收的事件（判定顺序照 §2） */
typedef enum {
    SPI_RX_NEED_MORE = 0,    /* 这一帧还没收完 */
    SPI_RX_FRAME,            /* 收到完整且 CRC 正确的请求帧 */
    SPI_RX_BAD_CRC,          /* 收完了但 CRC 不对（设备侧回 ERROR）*/
    SPI_RX_TOO_LONG,         /* LEN > MAX_FRAME（设备侧回 ERROR）*/
    SPI_RX_IGNORED           /* 本事务已收完一帧（响应阶段）或字节落在 CS 之外 */
} spi_rx_ev_t;

typedef struct {
    uint8_t  hdr[SPI_PROTO_HDR];
    uint8_t  hdr_idx;
    uint8_t  cmd;                        /* 已去掉 bit7 */
    uint16_t len;
    uint16_t idx;
    uint8_t  buf[SPI_PROTO_MAX_FRAME];
    uint8_t  done;                       /* 本事务已收完一帧（响应阶段不再收）*/
} spi_proto_rx_t;

/* ---- 接收状态机（设备侧）---- */
void     spi_proto_rx_reset(spi_proto_rx_t *rx);
void     spi_proto_cs_start(spi_proto_rx_t *rx);   /* NSS 下降沿：新事务 */
void     spi_proto_cs_end(spi_proto_rx_t *rx);     /* NSS 上升沿：事务结束 */
spi_rx_ev_t spi_proto_rx_byte(spi_proto_rx_t *rx, uint8_t b);
uint8_t  spi_proto_rx_cmd(const spi_proto_rx_t *rx);
/* 声明的 LEN（请求帧头里的那个值；too_long 时它 > MAX_FRAME）*/
uint16_t spi_proto_rx_declared_len(const spi_proto_rx_t *rx);
/* 已收到的载荷；**只有整帧到齐且 LEN ≤ MAX_FRAME 时**才返回 buffer（否则 NULL/0）——
 * 免得调用方拿着一个超过缓冲的长度去读（实测：too_long 时拿 48076 当长度直接崩）。*/
const uint8_t *spi_proto_rx_payload(const spi_proto_rx_t *rx, uint16_t *len);

/* ---- 编码 ---- */
/* 帧校验：请求用原 cmd；应答用**去掉 bit7** 的 cmd（与主机侧 parse 一致）*/
uint8_t spi_proto_crc(uint8_t cmd, const uint8_t *payload, uint16_t len);

/* 构造应答帧到 out（含 CRC），返回帧总长（4+len）；0 = outcap 不够。
 * ⚠ 允许 `out == payload`（就地搬）：先写 4 字节头，载荷**向前**拷（dst > src，安全），
 *   设备侧 DATA_RX 就是"载荷先落在 tx 缓冲里、随后就地把头补上"。*/
uint16_t spi_proto_build_resp(uint8_t *out, size_t outcap, uint8_t cmd,
                              const uint8_t *payload, uint16_t len);

#endif /* __SPI_PROTO_H__ */
