# ORPAH 批量合规测试报告

- 时间：2026-09-12 20:40:51
- git HEAD：`9ef98a9`
- 解释器：3.13.14 @ C:\Python313\python.exe
- 结论：**全部通过**（18/18 套件通过）

## 套件结果

| 套件 | 脚本 | 结果 | 耗时 | 说明 |
|---|---|---|---|---|
| 运动/定位数据源 | `test_motion.py` | ✅ PASS | 0.1s | 通过 |
| 密钥生命周期 | `test_keys.py` | ✅ PASS | 0.1s | 通过 |
| 防 spoof（离线逐条） | `test_spoof.py` | ✅ PASS | 0.1s | 通过 |
| 告警规则（含处置态） | `test_alerts.py` | ✅ PASS | 0.1s | 通过 |
| 指标面板纯计算 | `test_metrics.py` | ✅ PASS | 0.1s | 通过 |
| 时钟可信（ts=0 无 RTC） | `test_clock.py` | ✅ PASS | 0.5s | 通过 |
| IoTDB 审计/时间窗 | `test_tsdb_audit.py` | ✅ PASS | 0.5s | 通过 |
| UI 服务器契约 | `test_server.py` | ✅ PASS | 0.1s | 通过 |
| 批量合规用例（黄金样本/SN 边界/报文） | `checks_batch.py` | ✅ PASS | 0.1s | 通过 |
| 降级策略（§8.2 选级 / §8.3 服务端） | `test_levels.py` | ✅ PASS | 0.1s | 通过 |
| 抓包解析 / 双源对照 | `test_capture.py` | ✅ PASS | 0.1s | 通过 |
| 设备时钟漂移（长基线） | `demo_clock.py` | ✅ PASS | 0.1s | 通过 |
| 定位内核（pos.js，node 跑原文） | `test_posjs.py` | ✅ PASS | 0.1s | 通过 |
| L1 端到端 | `demo_l1.py` | ✅ PASS | 1.3s | 通过 |
| L2 消息流 | `demo_l2.py` | ✅ PASS | 2.2s | 通过 |
| L3 多 Router 漫游/去重 | `demo_l3.py` | ✅ PASS | 4.2s | 通过 |
| L3b 主动拉表 | `demo_l4.py` | ✅ PASS | 1.1s | 通过 |
| 防 spoof 空口端到端 | `demo_spoof.py` | ✅ PASS | 1.7s | 通过 |

## 关键输出

### 运动/定位数据源 — PASS（0.1s）

    == 1. �����뼸�� ==
    == 2. pos ȷ������������ ==
    == 3. �����ԣ���˲�ƣ� ==
    == 4. RSSI ·����Ļ��� ==
    == 4b. ǯλҪ��ס�����Ľ����2026-09-12 ��飩 ==
    == 5. ��·����һ�£���ʾ���ݿ����ԣ� ==
      OK   truth_at�������� �� �ձ���ҳ����ʾ�������á������� 0��
    ȫ��ͨ��

### 密钥生命周期 — PASS（0.1s）

    == 1. ǩ�����ݵȣ� ==
    == 2. ��ǩ���� 1 ���� ==
    == 3. �ֻ�����Կ�����ޡ��¾ɶ����� ==
    == 4. ���޵��� �� ���� ==
    == 5. grace_sec=0����Կ����ʧЧ ==
    == 6. ��ǰǿ������ ==
      OK   ��һ����gen=2��ǩ�ı����õ� 1 ���Ŀ��� �� �ܣ����β��ܴ���
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

### 时钟可信（ts=0 无 RTC） — PASS（0.5s）

    == 1. effective_ts 归一化规则（唯一入口，各层共用）==
    == 1b. 能力声明 cap（设备自报“有无 RTC”）==
    == 1c. ts_usable：判断“设备的时间能不能用” ==
    == 2. 验签的时间窗（ts=0 跳过窗口，仅靠 nonce 防重放）==
    == 3. 端到端（进程内 UDP）：ts=0 的报告落库时刻 + 审计留痕 ==
    == 4. 设备时钟偏移/漂移估计 ==
      OK   并发：4 写 × 50 条 + 2 读线程 → 无异常且一条不丢
    时钟可信测试全部通过

### IoTDB 审计/时间窗 — PASS（0.5s）

    == 1. actor �ֶ� ==
    == 2. query_events �ض� actor ==
    == 3. ������������ ==
    == 4. ʱ�䴰��ѯ���ط��ã� ==
    == 6. ·������۲⣨��·������λ������Դ�� ==
    == 7. ������������ ==
      OK   �Ϸ�ֵ��Ч
    ȫ��ͨ��

### UI 服务器契约 — PASS（0.1s）

    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 2] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 3] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=high accepted=True
    [server] [id 1] ORPAH-ID-REPORT <- 127.0.0.1:12345: sn=CN-WH01-9AF3C1D2 alg=ES256 level=0 trust=- accepted=False
    Ran 23 tests in 0.011s
    OK

### 批量合规用例（黄金样本/SN 边界/报文） — PASS（0.1s）

    == 1. 黄金样本（校验位只算 ORG-UNIQUE，不含 CC）==
    == 2. SN 边界（格式：CC-ORG-UNIQUE[-CHECK]，Crockford Base32 去 I L O U）==
    == 3. SN 解析（注册时按 SN 回填 cc/org，不信任前端传值）==
    == 4. 报文编解码边界（通用 JSON 公共头）==
      OK   parse_eth_frame：ethertype 不符 → None
    批量用例：全部通过

### 降级策略（§8.2 选级 / §8.3 服务端） — PASS（0.1s）

    == 1. ��8.2 ѡ�����̣���ֵ���� ==
    == 2. ��8.1 ӳ����뼶��ȡֵ�� ==
    == 3. Device.report �Զ�ѡ�� ==
    == 4. ��8.3 verify_report �� degraded / coverage_only ==
    == 5. counts_as_presence���ܲ��ܵ�����Ա���֡��� ==
    == 6. �����澯����8.3�� ==
      OK   ���� crit ���ڣ�˳��ͬ���� since��  ['case_overtime', 'sig_fail_rate']
    ȫ��ͨ��

### 抓包解析 / 双源对照 — PASS（0.1s）

    == 1. pcap ������д������ ==
    == 2. ��ʽ������볳������Ĭ������ ==
    == 3. ��������� ==
    == 4. ˫Դ���գ�ֻ������ӳ�䣩 ==
    == 5. ���� JSON ��ȡ ==
    == 6. CLI ð�̣�����һ�飬�˳���Ҫ�ԣ� ==
      OK   --json �ṹ�� summary+rows �� rows ȫ��  {'frames': 8, 'orpah': 5, 'by_type': {'ORPAH-REQ-CONNECT': 1, 'ORPAH-REPORT': 2, 'ORPAH-ACCESS-INFO': 1, 'ORPAH-ID-REPORT': 1}, 'errors': {'not-orpah': 1, 'bad-json': 1, 'bad-frame': 1}, 'linktype': 1, 'linktype_name': 'Ethernet'}
    ȫ��ͨ��

### 设备时钟漂移（长基线） — PASS（0.1s）

    --- A 时钟准（跑 1h）---
      [PASS] A：offset ≈ -0.5s（整数秒截断的固有偏置，不是设备真的慢 0.5s）
      [PASS] A：漂移不给数 —— 原因=noise（噪声里看不出趋势，不编 0 也不编别的）
    --- B 晶振偏快 +200ppm（跑 1h）---
      [PASS] B：offset ≈ +0.2s（当前时刻的偏差：漂移 1h 累计 +0.72s − 截断 0.5s）
      [PASS] B：漂移估出 +200ppm（晶振级，短窗做不到）

### 定位内核（pos.js，node 跑原文） — PASS（0.1s）

      OK   RSSI→距离→RSSI 往返（A=-40 n=2.5, -70dBm）
      OK   三边定位（精确距离）复原 (5,5)
      OK   WLS：远端差站（+40m）比等权线性解明显更接近真值（误差比 < 0.5）
      OK   WLS：标准入参（{s,dist}）在精确距离下复原 (5,5)（证明读的是 o.s.x/o.s.y）
      OK   椭圆：特征值→半轴（√(5.991·4) / √(5.991·1)，长短轴比 2）
      OK   椭圆：退化协方差（近乎共线）→ degenerate=true（半径仍可给，形状不可信）
      OK   cdfOf：空输入 → 各项 null（不许给 0 假装量过）
    定位内核（pos.js）全部通过

### L1 端到端 — PASS（1.3s）

    === ORPAH L1 验收 ===
    结果: [PASS]

### L2 消息流 — PASS（2.2s）

    --- 分支一：走失库未命中 sn=CN-WH01-9AF3C1D2 ---
    --- mark 走失 sn=CN-WH01-9AF3C1D2（Server 下发 LOST-TABLE）---
    --- 分支二：走失库命中 sn=CN-WH01-9AF3C1D2 ---
    === ORPAH L2 验收 ===
    分支一(未命中 NOT-TRACKED): PASS
    分支二(命中 TRACKED): PASS

### L3 多 Router 漫游/去重 — PASS（4.2s）

    --- 阶段A：sn=CN-WH01-9AF3C1D2 在 R1 网络（2 条，未 mark）---
    --- 阶段B：sn=CN-WH01-9AF3C1D2 漫游到 R2 网络（seq 续 3）---
    --- 阶段C：mark 走失 sn=CN-WH01-9AF3C1D2（在 R2 网络）---
    --- 阶段D：sn=CN-WH01-9AF3C1D2 在 R2 再次会话（应 tracked=True）---
    --- 阶段E：去重测试（重发已接受的 seq=4）---
    --- 阶段F：SN 校验（非法 sn → FORMAT-ERR）---

### L3b 主动拉表 — PASS（1.1s）

    --- 模拟 Router 重启（清空本地缓存 + 未同步）---
    --- Server untrack sn=CN-WH01-9AF3C1D2（变更推送，Router 无需再拉）---
    --- 关联号 rid：拉表应答 vs Server 主动推送 ---
      [PASS] REQ 带 rid（type 正确）
      [PASS] 应答原样回显 rid
      [PASS] 主动推送不带 rid

### 防 spoof 空口端到端 — PASS（1.7s）

      无认证空口防 spoof 端到端演示
      被冒充设备 SN : CN-WH01-9AF3C1D2
      攻击者 SN    : CN-WH01-PZWRHJW5DT-03（未登记 → 服务器不认识）
      链路          : Client→STA→空口→AP→Router→UDP:19847→Server
      用例数        : 13（含 1 条合法对照）
    [server] 监听 127.0.0.1:19847 (UDP)，等待 ORPAH 报文…
      🎉 防 spoof 端到端验收全部通过
    ==========================================================================

