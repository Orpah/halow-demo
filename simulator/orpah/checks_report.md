# ORPAH 批量合规测试报告

- 时间：2026-09-12 15:36:05
- git HEAD：`38d1027`
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
| IoTDB 审计/时间窗 | `test_tsdb_audit.py` | ✅ PASS | 0.6s | 通过 |
| UI 服务器契约 | `test_server.py` | ✅ PASS | 0.1s | 通过 |
| 批量合规用例（黄金样本/SN 边界/报文） | `checks_batch.py` | ✅ PASS | 0.0s | 通过 |
| L1 端到端 | `demo_l1.py` | ✅ PASS | 1.4s | 通过 |
| L2 消息流 | `demo_l2.py` | ✅ PASS | 2.2s | 通过 |
| L3 多 Router 漫游/去重 | `demo_l3.py` | ✅ PASS | 4.3s | 通过 |
| L3b 主动拉表 | `demo_l4.py` | ✅ PASS | 1.5s | 通过 |
| 防 spoof 空口端到端 | `demo_spoof.py` | ✅ PASS | 1.6s | 通过 |

## 关键输出

### 运动/定位数据源 — PASS（0.1s）

    == 1. �����뼸�� ==
    == 2. pos ȷ������������ ==
    == 3. �����ԣ���˲�ƣ� ==
    == 4. RSSI ·����Ļ��� ==
    == 4b. ǯλҪ��ס�����Ľ����2026-09-12 ��飩 ==
    == 5. ��·����һ�£���ʾ���ݿ����ԣ� ==
      OK   replay.html ��ҳȡ /api/config��HTML ���ֻ�Ƕ��ף�
    ȫ��ͨ��

### 密钥生命周期 — PASS（0.1s）

    == 1. ǩ�����ݵȣ� ==
    == 2. ��ǩ���� 1 ���� ==
    == 3. �ֻ�����Կ�����ޡ��¾ɶ����� ==
    == 4. ���޵��� �� ���� ==
    == 5. grace_sec=0����Կ����ʧЧ ==
    == 6. ��ǰǿ������ ==
      OK   �ɸ�ʽ���������ǩ
    all key lifecycle tests passed

### 防 spoof（离线逐条） — PASS（0.1s）

    == 1. �嵥��Ǣ ==
    == 2. �����þ������ߣ� ==
    == 3. �������� ==
    == 4. ����ȷʵ�Ķ��˱��ģ����ǰѺϷ�����ԭ������һ�飩 ==
    == 5. ˳���޹أ�revoked ����ʱ�⣬����Ⱦ�������� keystore�� ==
      OK   revoked ����ǰ vs ��������� (kind, �þ�) ��ȫһ��  ����� 2 �ڵ�Ĭ��˳��Աȣ�����˳��ͬ���ʰ����ϱȣ�
    ȫ��ͨ��

### 告警规则（含处置态） — PASS（0.1s）

    PASS  ��δ�ϱ�������/��ʧ�еĶ�����ͣ��/���ϲ���
    PASS  ��δ�ϱ����� gap �ҵȼ� warn
    PASS  C��Ĭ�� no_report ������ֵ 300s��ORPAH_ALERT_NO_REPORT_CRIT_SEC��
    PASS  C��Ĭ�� case_handled ������ֵ 48h��ORPAH_ALERT_CASE_HANDLED_CRIT_SEC��ע��������ֵ CASE_HANDLED_SEC=24h ��������ͬ������
    PASS  C���չ��𲽵�δ�������� �� warn
    PASS  C������������ �� crit

### 指标面板纯计算 — PASS（0.1s）

    PASS  ǩ��������/ͨ��/����
    PASS  ǩ����ʧ���� 1/4
    PASS  ǩ�����㷨�ֲ�
    PASS  ǩ�������������¼�����ͳ��
    PASS  ǩ����ȡ���� alg �� unknown�����£�
    PASS  ǩ���������� �� fail_ratio=None������ 0��

### 时钟可信（ts=0 无 RTC） — PASS（0.4s）

    == 1. effective_ts 归一化规则（唯一入口，各层共用）==
    == 2. 验签的时间窗（ts=0 跳过窗口，仅靠 nonce 防重放）==
    == 3. 端到端（进程内 UDP）：ts=0 的报告落库时刻 + 审计留痕 ==
      OK   留痕：ts_src=device（时间来自设备）
    时钟可信测试全部通过

### IoTDB 审计/时间窗 — PASS（0.6s）

    == 1. actor �ֶ� ==
    == 2. query_events �ض� actor ==
    == 3. ������������ ==
    == 4. ʱ�䴰��ѯ���ط��ã� ==
    == 6. ·������۲⣨��·������λ������Դ�� ==
    == 7. ������������ ==
      OK   �Ϸ�ֵ��Ч
    ȫ��ͨ��

### UI 服务器契约 — PASS（0.1s）

    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=none level=3 trust=none accepted=True
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 2] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    Ran 16 tests in 0.009s
    OK

### 批量合规用例（黄金样本/SN 边界/报文） — PASS（0.0s）

    == 1. 黄金样本（校验位只算 ORG-UNIQUE，不含 CC）==
    == 2. SN 边界（格式：CC-ORG-UNIQUE[-CHECK]，Crockford Base32 去 I L O U）==
    == 3. SN 解析（注册时按 SN 回填 cc/org，不信任前端传值）==
    == 4. 报文编解码边界（通用 JSON 公共头）==
      OK   parse_eth_frame：ethertype 不符 → None
    批量用例：全部通过

### L1 端到端 — PASS（1.4s）

    === ORPAH L1 验收 ===
    结果: [PASS]

### L2 消息流 — PASS（2.2s）

    --- 分支一：走失库未命中 sn=CN-WH01-9AF3C1D2 ---
    --- mark 走失 sn=CN-WH01-9AF3C1D2（Server 下发 LOST-TABLE）---
    --- 分支二：走失库命中 sn=CN-WH01-9AF3C1D2 ---
    === ORPAH L2 验收 ===
    分支一(未命中 NOT-TRACKED): PASS
    分支二(命中 TRACKED): PASS

### L3 多 Router 漫游/去重 — PASS（4.3s）

    --- 阶段A：sn=CN-WH01-9AF3C1D2 在 R1 网络（2 条，未 mark）---
    --- 阶段B：sn=CN-WH01-9AF3C1D2 漫游到 R2 网络（seq 续 3）---
    --- 阶段C：mark 走失 sn=CN-WH01-9AF3C1D2（在 R2 网络）---
    --- 阶段D：sn=CN-WH01-9AF3C1D2 在 R2 再次会话（应 tracked=True）---
    --- 阶段E：去重测试（重发已接受的 seq=4）---
    --- 阶段F：SN 校验（非法 sn → FORMAT-ERR）---

### L3b 主动拉表 — PASS（1.5s）

    --- 模拟 Router 重启（清空本地缓存 + 未同步）---
    --- Server untrack sn=CN-WH01-9AF3C1D2（变更推送，Router 无需再拉）---
    === ORPAH Router 主动拉表 验收 ===
      [PASS] ① mark 后启动 Router 即主动拉表追平（不依赖推送）
      [PASS] ② 首次 REQ 答 tracked=True（启动拉表就绪）
      [PASS] ③ 重启后 REQ 同步拉表、首问即权威

### 防 spoof 空口端到端 — PASS（1.6s）

      无认证空口防 spoof 端到端演示
      被冒充设备 SN : CN-WH01-9AF3C1D2
      攻击者 SN    : CN-WH01-2TFH2A65KM-61（未登记 → 服务器不认识）
      链路          : Client→STA→空口→AP→Router→UDP:19847→Server
      用例数        : 12（含 1 条合法对照）
    [server] 监听 127.0.0.1:19847 (UDP)，等待 ORPAH 报文…
      🎉 防 spoof 端到端验收全部通过
    ==========================================================================

