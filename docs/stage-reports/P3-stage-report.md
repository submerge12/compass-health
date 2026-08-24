# P3 阶段报告 — M05 统一饮食记录（M11 待 pi_harness）

**执行日期：** 2026-08-24（紧接 P2）
**范围：** §20 P3 的 M05 全部。M11（新主体/故障切换）依赖 pi_harness 仓库，仍 BLOCKED_ENV。

## 一、交付物

### compress_health_agent

| 提交 | 内容 |
|---|---|
| `eb983e1` | **DietLogV2**：`diet_logs` 新增 `idempotency_key`（每用户 partial unique，旧行 NULL 不受影响）、`estimate_confidence`、`uncertain`、`correction_of_id`、`superseded_by_id`、`journey_id`；`src/domain/diet-log-service.ts` 三段命令流；display-server v1 端点；6 条 DB 不变量测试 |
| `2b6b2a9` | live 验证发现的两个投影缺陷修复：correct 后未重建投影、投影统计把被取代行一起计入 |

### compass-health

- `13ee53c`：BFF 对 diet v2 三端点的代理合同测试（trace 头在 commit 跳验证）。

## 二、关键行为（测试 + live 双重固化）

| 场景 | 行为 |
|---|---|
| 高置信描述（"牛肉150克"） | preview=ok → commit 直接落库，uncertain=false，outbox 事件同事务 |
| 同幂等键重试 | 返回**原始行**（replayed=true），不产生重复事实——P0 基线记录的"重复提交产生重复事实"缺陷就此关闭 |
| 无法解析描述 | commit 直接拒绝（needs_confirmation + candidates），fallback 猜测值**绝不**变成静默事实；确认后的 items 以 overrideEstimate 提交为已审核事实 |
| 修正 | 新行 correction_of_id 指向原行，原行标 superseded_by_id；修正重放返回同一修订行；有效日清单排除被取代行 |
| expectedRevision 冲突 | 抛 state_conflict（409 上游），不静默覆盖 |
| 每日状态 | 只统计有效修订：live 实测 commit 240kcal → correct 320kcal → daily-state 显示 count=1 / kcal=320 |

**迁移注记**：drizzle-kit push 对加唯一约束要求交互式 truncate 确认（表内有真实数据），已拒绝并改用手动 `ALTER TABLE ... ADD COLUMN` + **partial unique index**（仅非 NULL 键参与，兼容旧行）；schema.ts 用 `uniqueIndex().where()` 与库内保持一致。

**测试期间发现的语言学事实**："牛肉 150 克"（带空格）会被分词成"牛肉"+"150 克"，后者不可解析 → uncertain（估算器设计使然）；自然书写"牛肉150克"则高置信直存。此行为已写入提交说明，M09 语音词典需覆盖。

## 三、回归与验收状态

- agent：**393 passed**（+6 diet v2 不变量）
- compass-health：**84 passed + 1 skip**（+1 BFF 代理）
- P0 旅程基线按设计"翻转"：J01 缺列断言改为保护新列的正向不变量
- J01 验收标准对照：同一 log id 进入事实与看板 ✅（live 验证）；重试不重复 ✅；修正 lineage ✅；估算 confidence 可见 ✅（uncertain/confidence 列 + preview status）。剩余项"Web 页面 UI 接入新端点"属 M10/P7 前端工作。

## 四、阶段位置

P3 的 agent 侧核心完成。剩余：
1. **M11**（primary profile / legacy fallback / J12）：BLOCKED_ENV，等 pi_harness。
2. Web 前端 diet.js 改调 v1 端点：可与 M10 统一做，当前 v1 API 已可用（经 BFF）。

下一步建议进入 **P4 结构化训练**（M06/M07：训练域、A/B/C 计划版本、逐组记录、替代引擎、反思）——它只依赖 P2 已就绪的 plan_versions 和 daily state，无需外部输入。
