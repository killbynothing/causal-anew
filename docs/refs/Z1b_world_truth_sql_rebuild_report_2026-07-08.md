# Z1b world_truth.sql 重建差异报告

- 生成时间：2026-11-12 13:17:45Z
- 源库：`data/world_truth.db`
- SQL dump：`data/world_truth.sql`
- 表数量：原库 27 / 重建 27
- 排除的运行态可变表：`delta_ledger, delta_sediment, run_bonds, run_meta`
- 结论：**PASS**

## 差异摘要

- 静态真值表级 row count + ordered row sha256 全部一致。

## 四支柱重建库验证

- exit_code：0

```text
mech_invariant_suite v0.1 ｜ 四支柱运行时断言

[支柱一] 不可回滚常量 / E_SELF_REF
  [PASS] 回滚固定底(CC.RYUYA_DEATH)契约必报 E_SELF_REF
  [PASS] 10 次常量干涉 → 10 条 SELF_REF_LOCK
  [PASS] 世界态在常量干涉后不变

[支柱二] 一秒之差 / xline 恒定 1.000s
  [PASS] 200 条混合信道 t_send-t_observed 方差 == 0
  [PASS] 均值恒等于 1000ms
  [PASS] 修哉发现戏 GROUP BY channel 逐位 == 1.000000

[支柱三] 锚点信道 SNR / 干涉永不免费
  [PASS] 同型连打：cost5 > cost1
  [PASS] 新型干涉 lt_filter 增量 < 同型
  [PASS] snr 归零 → 干涉选项损坏态(非可点)

[支柱四] 双跳者相干矩阵
  [PASS] aligned 场景实扣 < 单独干涉
  [PASS] opposed 场景产生 LT 告警
  [PASS] 尘叔在场旁观 NPC meta_awareness 增速 > 基线

结果：12 通过，0 失败
```

## 待人裁边界

- 本报告证明 SQL dump 可重建当前静态真值表并通过四支柱断言。
- `run_bonds` 为运行态/玩家态可变表，不纳入静态真值零差异口径。
- 是否让 `data/world_truth.db` 退出 git 跟踪，仍需 D2② 人裁后另行执行。
