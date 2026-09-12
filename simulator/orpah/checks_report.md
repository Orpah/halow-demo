# ORPAH 批量合规测试报告

- 时间：2026-09-12 14:39:17
- git HEAD：`8bea28f`
- 解释器：3.13.14 @ C:\Python313\python.exe
- 结论：**全部通过**（14/14 套件通过）

## 套件结果

| 套件 | 脚本 | 结果 | 耗时 | 说明 |
|---|---|---|---|---|
| 运动/定位数据源 | `test_motion.py` | ✅ PASS | 0.1s | 通过 |
| 密钥生命周期 | `test_keys.py` | ✅ PASS | 0.1s | 通过 |
| 防 spoof（离线逐条） | `test_spoof.py` | ✅ PASS | 0.1s | 通过 |
| 告警规则（含处置态） | `test_alerts.py` | ✅ PASS | 0.1s | 通过 |
| 指标面板纯计算 | `test_metrics.py` | ✅ PASS | 0.1s | 通过 |
| 时钟可信（ts=0 无 RTC） | `test_clock.py` | ✅ PASS | 0.4s | 通过 |
| IoTDB 审计/时间窗 | `test_tsdb_audit.py` | ✅ PASS | 0.5s | 通过 |
| UI 服务器契约 | `test_server.py` | ✅ PASS | 0.1s | 通过 |
| 批量合规用例（黄金样本/SN 边界/报文） | `checks_batch.py` | ✅ PASS | 0.1s | 通过 |
| L1 端到端 | `demo_l1.py` | ✅ PASS | 1.4s | 通过 |
| L2 消息流 | `demo_l2.py` | ✅ PASS | 2.3s | 通过 |
| L3 多 Router 漫游/去重 | `demo_l3.py` | ✅ PASS | 4.2s | 通过 |
| L3b 主动拉表 | `demo_l4.py` | ✅ PASS | 1.6s | 通过 |
| 防 spoof 空口端到端 | `demo_spoof.py` | ✅ PASS | 1.5s | 通过 |

## 关键输出

### 运动/定位数据源 — PASS（0.1s）

    == 1. 构造与几何 ==
    == 2. pos 确定性与周期性 ==
    == 3. 连续性（不瞬移） ==
    == 4. RSSI 路径损耗换算 ==
    == 5. 多路由器一致（演示数据可用性） ==
    == 5b. 测量噪声（无噪声时平滑/椭圆都没意义，所以演示数据必须带噪） ==
      OK   default() 复用同一实例
    全部通过

### 密钥生命周期 — PASS（0.1s）

    == 1. 签发（幂等） ==
    == 2. 验签（第 1 代） ==
    == 3. 轮换：旧钥进宽限、新旧都能验 ==
    == 4. 宽限到期 → 退役 ==
    == 5. grace_sec=0：旧钥立即失效 ==
    == 6. 提前强制退役 ==
      OK   旧格式导入后能验签
    all key lifecycle tests passed

### 防 spoof（离线逐条） — PASS（0.1s）

    == 1. 清单自洽 ==
    == 2. 逐条裁决（离线） ==
    == 3. 防线语义 ==
    == 4. 攻击确实改动了报文（不是把合法报文原样发了一遍） ==
    == 5. 顺序无关（revoked 用临时库，不污染传进来的 keystore） ==
      OK   revoked 排最前 vs 排最后，逐条 (kind, 裁决) 完全一致  （与第 2 节的默认顺序对比；两侧顺序不同，故按集合比）
    全部通过

### 告警规则（含处置态） — PASS（0.1s）

    PASS  长未上报：启用/走失中的都报，停用/报废不报
    PASS  长未上报：带 gap 且等级 warn
    PASS  C：默认 no_report 升级阈值 300s
    PASS  C：默认 case_handled 升级阈值 48h
    PASS  C：刚过起步但未到升级点 → warn
    PASS  C：超过升级点 → crit
    PASS  env：清后恢复默认
    all alert tests passed

### 指标面板纯计算 — PASS（0.1s）

    PASS  签名：总数/通过/被拒
    PASS  签名：失败率 1/4
    PASS  签名：算法分布
    PASS  签名：其它类型事件不进统计
    PASS  签名：取不到 alg → unknown（不猜）
    PASS  签名：无样本 → fail_ratio=None（不编 0）
    PASS  真实对象：立案→发现 400s（用真 CaseManager 的 events）
    全部通过

### 时钟可信（ts=0 无 RTC） — PASS（0.4s）

    == 1. effective_ts 归一化规则（唯一入口，各层共用）==
    == 2. 验签的时间窗（ts=0 跳过窗口，仅靠 nonce 防重放）==
    == 3. 端到端（进程内 UDP）：ts=0 的报告落库时刻 + 审计留痕 ==
      OK   留痕：ts_src=device（时间来自设备）
    时钟可信测试全部通过

### IoTDB 审计/时间窗 — PASS（0.5s）

    == 1. actor 字段 ==
    == 2. query_events 回读 actor ==
    == 3. 保留期限清理 ==
    == 4. 时间窗查询（回放用） ==
    == 6. 路由器侧观测（多路由器定位的数据源） ==
    == 7. 环境变量解析 ==
      OK   合法值生效
    全部通过

### UI 服务器契约 — PASS（0.1s）

    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=none level=3 trust=none accepted=True
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 2] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    Ran 16 tests in 0.010s
    OK

### 批量合规用例（黄金样本/SN 边界/报文） — PASS（0.1s）

    == 1. 黄金样本（校验位只算 ORG-UNIQUE，不含 CC）==
    == 2. SN 边界（格式：CC-ORG-UNIQUE[-CHECK]，Crockford Base32 去 I L O U）==
    == 3. SN 解析（注册时按 SN 回填 cc/org，不信任前端传值）==
    == 4. 报文编解码边界（通用 JSON 公共头）==
      OK   parse_eth_frame：ethertype 不符 → None
    批量用例：全部通过

### L1 端到端 — PASS（1.4s）

    === ORPAH L1 验收 ===
    Server 收到: 3 条  (sn 一致: True)
    结果: [PASS]

### L2 消息流 — PASS（2.3s）

    --- 分支一：走失库未命中 sn=CN-WH01-9AF3C1D2 ---
    --- mark 走失 sn=CN-WH01-9AF3C1D2（Server 下发 LOST-TABLE）---
    --- 分支二：走失库命中 sn=CN-WH01-9AF3C1D2 ---
    === ORPAH L2 验收 ===
    分支二(命中 TRACKED): PASS
    结果: [PASS]

### L3 多 Router 漫游/去重 — PASS（4.2s）

    --- 阶段A：sn=CN-WH01-9AF3C1D2 在 R1 网络（2 条，未 mark）---
    --- 阶段B：sn=CN-WH01-9AF3C1D2 漫游到 R2 网络（seq 续 3）---
    --- 阶段C：mark 走失 sn=CN-WH01-9AF3C1D2（在 R2 网络）---
    --- 阶段D：sn=CN-WH01-9AF3C1D2 在 R2 再次会话（应 tracked=True）---
    --- 阶段E：去重测试（重发已接受的 seq=4）---
    --- 阶段F：SN 校验（非法 sn → FORMAT-ERR）---
      [PASS] F 非法 SN → FORMAT-ERR 且不计数
    结果: [PASS]

### L3b 主动拉表 — PASS（1.6s）

    --- 模拟 Router 重启（清空本地缓存 + 未同步）---
    --- Server untrack sn=CN-WH01-9AF3C1D2（变更推送，Router 无需再拉）---
    === ORPAH Router 主动拉表 验收 ===
      [PASS] ④ 变更推送仍生效且 REQ 不再多拉
    结果: [PASS]

### 防 spoof 空口端到端 — PASS（1.5s）

    ==========================================================================
    ==========================================================================
    ==========================================================================
    ==========================================================================

