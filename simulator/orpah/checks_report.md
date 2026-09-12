# ORPAH 批量合规测试报告

- 时间：2026-09-12 13:00:57
- git HEAD：`eb04f99`
- 解释器：3.13.14 @ C:\Python313\python.exe
- 结论：**全部通过**（7/7 套件通过）

## 套件结果

| 套件 | 脚本 | 结果 | 耗时 | 说明 |
|---|---|---|---|---|
| 运动/定位数据源 | `test_motion.py` | ✅ PASS | 0.0s | 通过 |
| 密钥生命周期 | `test_keys.py` | ✅ PASS | 0.2s | 通过 |
| 防 spoof（离线逐条） | `test_spoof.py` | ✅ PASS | 0.1s | 通过 |
| 告警规则（含处置态） | `test_alerts.py` | ✅ PASS | 0.1s | 通过 |
| IoTDB 审计/时间窗 | `test_tsdb_audit.py` | ✅ PASS | 0.5s | 通过 |
| UI 服务器契约 | `test_server.py` | ✅ PASS | 0.1s | 通过 |
| 批量合规用例（黄金样本/SN 边界/报文） | `checks_batch.py` | ✅ PASS | 0.1s | 通过 |

## 关键输出

### 运动/定位数据源 — PASS（0.0s）

    == 1. 构造与几何 ==
    == 2. pos 确定性与周期性 ==
    == 3. 连续性（不瞬移） ==
    == 4. RSSI 路径损耗换算 ==
    == 5. 多路由器一致（演示数据可用性） ==
    == 5b. 测量噪声（无噪声时平滑/椭圆都没意义，所以演示数据必须带噪） ==
      OK   default() 复用同一实例
    全部通过

### 密钥生命周期 — PASS（0.2s）

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

    PASS  长未上报：只报超时的启用设备
    PASS  长未上报：带 gap 且等级 warn
    PASS  长未上报：等于阈值不告警
    PASS  走失超时：只报 open 的案件
    PASS  走失超时：等级 crit
    PASS  走失超时：case_key 可去重
    PASS  env：清后恢复默认
    all alert tests passed

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

