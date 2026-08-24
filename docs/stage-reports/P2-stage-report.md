# P2 阶段报告 — M03/M04/M14：状态、版本、事件与可观察性

**执行日期：** 2026-08-24（紧接 P1，同一工作区）
**范围：** §20 P2 的 M03 核心（每日状态/事实/约束）、M04 核心（outbox/投影 worker/checkpoint）、M14 基础（确认策略分级）。

## 一、交付物

### compress_health_agent（4 个新提交）

| 提交 | 内容 |
|---|---|
| `32c38af` | **9 张新表**（compass_health schema）：`plan_versions` + `active_plan_assignments`（不可变版本 + 每 (user,scope) 原子 active 指针）、`health_observation_events`（append-only 睡眠/疲劳/恢复/疼痛事实）、`health_constraints`（strictest-wins 限制 + 解除审计链）、`user_decision_events`、`outbox_events`、`interaction_events`、`projection_checkpoints`、`daily_health_state_projection` |
| `648a5a4` | `src/domain/daily-state.ts`（观察事实+outbox 同事务、DailyHealthStateV1 投影构建/重建/读取、约束生命周期、幂等账本、CONFIRMATION_POLICY 七级风险矩阵）；`src/domain/projection-worker.ts`（outbox 消费、有界重试、dead-letter、安全重放、checkpoint 全量重建）；display-server v1 路由；5 条 DB 不变量测试 |
| `6398e0c` | daily-state 无投影日返回显式空结构（status=rebuilding, missing=true）而非空 body |

### compass-health（1 个新提交）

- `032cb04`：BFF 对 `/api/domain/v1/daily-state`、`/api/domain/v1/observations` 的代理合同测试（复用 M01 通用代理，无需新路由代码——这正是 BFF 设计的收益）。

## 二、验证结果

**测试**：
- agent：**387 passed**（382 + 5 条 DB 不变量）
- compass-health：**83 passed + 1 skipped**

**DB 不变量测试覆盖的验收门**：
1. 观察插入 → 事实行 + outbox 行同事务原子落地；
2. 投影重建内容确定性、revision 单调递增；
3. **J09 故障注入**：worker 失败不回滚已提交事实、attempts 耗尽进 dead-letter、`replayDeadLetters()` 后重放收敛、读模型诚实报告队列深度；
4. 约束生命周期：add→active→lift 留审计字段（liftedAt/liftedByActor），不物理删除；
5. 幂等键重复拒绝（DuplicateIdempotencyKeyError）。

**真实端到端实测**（领域 API 服务鉴权模式 + X-External-User-ID）：
```
GET  /api/v1/daily-state?date=…   → missing:true, status=rebuilding
POST /api/v1/observations (sleep) → eventId 返回
POST /api/v1/constraints (knee)   → constraintId 返回
GET  /api/v1/daily-state          → status=fresh, observations=[sleep],
                                    activeConstraints 经 /constraints 可查，
                                    pendingOutboxEvents=1（诚实可见）
```
测试数据已清理，容器恢复原状。

**schema 迁移**：`db:push` 已应用到真实库，9 张表建成，既有 6 用户数据完好（P0 快照可回滚）。

## 三、M01 验收项的 P2 补充

"同一 journey id 在前端错误/FastAPI 日志/领域回执关联"——现在有了持久化载体：BFF 传播的 request/journey id 进入 `interaction_events` 与 outbox 事件，跨服务 trace 不再只存在于日志文件。

## 四、P2 完成条件核对（§21）

| 条件 | 状态 |
|---|---|
| DailyHealthStateV1 覆盖必需字段 | ✅ v1 结构落地（activePlans/observations/constraints/饮食水运动汇总/projection.status）；训练域字段随 P4 填充 |
| plan version immutable | ⚠️ 表结构与 active 指针就绪，激活/回滚命令流在 P3/P4 接 handler 时闭环 |
| expected revision/idempotency 生效 | ◐ idempotency ✅；expectedStateRevision 冲突路径已在 daily-state 定义异常类，命令级接线随 P3 DietLogV2 落地 |
| outbox/projection 可重放 | ✅ 测试固化 |
| J09 通过 | ✅ 故障注入测试 + 实测 |
| 风险/确认 policy 有代码测试 | ◐ CONFIRMATION_POLICY 分级已入代码；完整确认矩阵测试随 M14 收尾 |

**结论**：P2 核心达成，两个半成品项（plan version 命令闭环、expectedRevision 接线）按计划本来就依赖 P3 的 DietLogV2 命令模型，不构成进入 P3 的阻塞。

## 五、下一步

P3（M05 统一饮食记录 + M11 新主体）：DietLogV2 preview/commit/correct 命令 + confidence/correction chain 列 + expectedRevision/idempotency-key 正式接入写路径。pi_harness 相关部分仍等仓库纳入。
