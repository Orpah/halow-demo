# ORPAH 批量合规测试报告

- 时间：2026-09-12 13:20:09
- git HEAD：`4e21acc`
- 解释器：3.13.14 @ C:\Python313\python.exe
- 结论：**全部通过**（8/8 套件通过）

## 套件结果

| 套件 | 脚本 | 结果 | 耗时 | 说明 |
|---|---|---|---|---|
| 运动/定位数据源 | `test_motion.py` | ✅ PASS | 0.1s | 通过 |
| 密钥生命周期 | `test_keys.py` | ✅ PASS | 0.2s | 通过 |
| 防 spoof（离线逐条） | `test_spoof.py` | ✅ PASS | 0.1s | 通过 |
| 告警规则（含处置态） | `test_alerts.py` | ✅ PASS | 0.1s | 通过 |
| 时钟可信（ts=0 无 RTC） | `test_clock.py` | ✅ PASS | 0.4s | 通过 |
| IoTDB 审计/时间窗 | `test_tsdb_audit.py` | ✅ PASS | 0.6s | 通过 |
| UI 服务器契约 | `test_server.py` | ✅ PASS | 0.1s | 通过 |
| 批量合规用例（黄金样本/SN 边界/报文） | `checks_batch.py` | ✅ PASS | 0.1s | 通过 |

## 关键输出

### 运动/定位数据源 — PASS（0.1s）

    == 1. �����뼸�� ==
    == 2. pos ȷ������������ ==
    == 3. �����ԣ���˲�ƣ� ==
    == 4. RSSI ·����Ļ��� ==
    == 5. ��·����һ�£���ʾ���ݿ����ԣ� ==
    == 5b. ����������������ʱƽ��/��Բ��û���壬������ʾ���ݱ�����룩 ==
      OK   default() ����ͬһʵ��
    ȫ��ͨ��

### 密钥生命周期 — PASS（0.2s）

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

    PASS  ��δ�ϱ���ֻ����ʱ�������豸
    PASS  ��δ�ϱ����� gap �ҵȼ� warn
    PASS  ��δ�ϱ���������ֵ���澯
    PASS  ��ʧ��ʱ��ֻ�� open �İ���
    PASS  ��ʧ��ʱ���ȼ� crit
    PASS  ��ʧ��ʱ��case_key ��ȥ��
    PASS  env�����ָ�Ĭ��
    all alert tests passed

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

### 批量合规用例（黄金样本/SN 边界/报文） — PASS（0.1s）

    == 1. 黄金样本（校验位只算 ORG-UNIQUE，不含 CC）==
    == 2. SN 边界（格式：CC-ORG-UNIQUE[-CHECK]，Crockford Base32 去 I L O U）==
    == 3. SN 解析（注册时按 SN 回填 cc/org，不信任前端传值）==
    == 4. 报文编解码边界（通用 JSON 公共头）==
      OK   parse_eth_frame：ethertype 不符 → None
    批量用例：全部通过

