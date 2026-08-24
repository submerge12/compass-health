# 健康系统用户旅程基线注册表（M00 / P0）

**建立日期：** 2026-08-24
**审查基线提交（与修改计划一致，已验证）：**

- `compress_health_agent` `main@1c73205b48673efc0b24c8735e68f0dd2a7abf7f`（2026-07-20）
- `compass-health` `main@b1716fa50f529cfe63657f4c3469fadb8e2d8f20`（2026-07-06）

本目录是《健康系统基于现有代码的修改计划》M00 的落地产物。每条旅程记录：
场景 / 触发输入 / 当前表现 / 正确表现 / 根因阶段 / 修改位置 / 回归测试 / 验收标准。
后续每个阶段（P1+）合入时，必须把对应旅程的"当前表现"更新为实测结果，并链接回归测试。

## 环境与证据状态（建立当日实测）

| 项目 | 结果 | 说明 |
|---|---|---|
| agent 测试基线（无 DB） | 333 passed / 35 skipped | skip 全部为 DB 集成测试 |
| agent 测试基线（PostgreSQL :5433） | **378 passed / 0 failed** | 含新增 10 条旅程基线特征测试 |
| compass-health pytest 基线 | **73 passed / 0 failed** | 环境需钉 `bcrypt==4.0.1`（passlib 1.7.4 与 bcrypt 5.x 不兼容，非仓库缺陷） |
| PostgreSQL 实例 | 单用户 `external_id=holly-test`，tz `Asia/Shanghai`，17 张表 | 数据范围：diet_logs 2026-06-17；meal_plan 2026-06-18..24；exercise 4 条；physical_conditions 4 条；memory_records 0 |
| PG 回滚快照 | `p0-artifacts/compass_health_pg_snapshot_2026-08-24.sql`（SHA-256 `6825204e…`） | pg_dump 逻辑备份 |
| SQLite `compass.db` 盘点 | **BLOCKED_ENV** | 本环境没有真实 compass.db 副本；真实历史取舍属计划 §23 待确认事项 2 |
| Docker / pgvector | 容器 `compass-health-pg`（已存在的用户容器，仅启动未重建） | 数据卷 `compass-health-agent_pgdata` 保留 |

关键代码锚点（本次实测复核）：

- `frontend/js/api.js:645` — `AGENT_API_BASE` 默认 `http://127.0.0.1:8788`，浏览器直连领域服务。
- `start.bat` — 只启动 FastAPI :8000 与静态前端 :5500；不启动 PostgreSQL、不启动 :8788。
- `src/server/serve.ts` — Display API 整个进程共享单一 `ctx.userId`（固定单用户）。
- `src/tools/handlers.ts` `handleDailySummary` — 水 2000ml / 运动 30min / 2000kcal 目标硬编码。
- `diet_logs` 表 — 无 idempotency/confidence/correctionOf/supersededBy 列（旅程基线测试断言）。
- 同一输入重复 `handleLogMeal` → 产生重复事实行（旅程基线测试 J01 gap 断言）。

## 旅程注册表

### J01 饮食计划 → 实际饮食 → 当天统计

- **场景：** 用户已有七日餐单，午餐后记录"牛肉 150 克"，晚间查看当日统计。
- **触发输入：** `handleSetProfile` → `handleLogMeal(date, lunch, "牛肉 150 克")` ×1；重复提交 ×1；`handleDailySummary(date)`。
- **当前表现（实测）：** Agent 侧闭环成立：记录写入 PostgreSQL（source=agent），汇总同日读回一致（agent 基线测试通过）。但 (a) 重复提交产生两行重复事实；(b) 无置信度/修正链字段；(c) Web 页面"手动饮食记录"走 FastAPI→SQLite，不进入本统计；(d) 计划行无 plan_version。
- **正确表现：** 同一 `journeyId` 下计划版本、预览/提交、读回、看板使用同一 log id；重试幂等；修正保留 lineage；Web 与 Agent 写同一 PostgreSQL。
- **根因阶段：** ① 双数据源（架构）② 无幂等键（DB 约束）③ 无版本引用（schema）。
- **修改位置：** M01（BFF）、M02（SSOT 迁移）、M05（DietLogV2）。
- **回归测试：** `compress_health_agent/tests/acceptance/continuous-health-journeys.test.ts`（J01 段，现为特征测试，P3 翻转为验收断言）。
- **验收标准：** 计划 §8 J01：同一 log id 进入事实与看板；估算显示 confidence；重试不重复。

### J02 三分化训练逐组记录 — BLOCKED_DOMAIN

- **场景：** A 日训练，逐组记录重量/次数/RIR/肌肉感受/不适。
- **当前表现（实测 schema）：** `exercise_logs` 仅有 activityType/durationMinutes/calories/intensity/notes；无 training_sessions/sets/plan_items/plan_versions 表；无任何训练 handler。
- **正确表现：** prepare→start→record_set(幂等)→finish→reflection；刷新/重启可恢复；未知重量保持 null 不伪造。
- **根因阶段：** 领域缺失（训练域不存在）。
- **修改位置：** M06（P4）。**回归测试：** 基线测试 J02 todo。**验收：** §8 J02。

### J03 睡眠不足调整训练 — BLOCKED_DOMAIN（部分可探）

- **场景：** 每日先写睡眠和主观反馈，训练计划据此缩量或改休息。
- **当前表现（实测）：** `physical_conditions` 有 sleep_hours/resting_heart_rate 列，但 Agent 侧只有 `handleLogWeight` 一个身体状态入口（无 sleep/fatigue/pain handler——基线测试断言）；汇总不读睡眠；无 readiness policy。
- **正确表现：** 状态规则输出带睡眠 evidence 的执行/缩量/休息 proposal；接受后 active plan 真实变化。
- **根因阶段：** 领域缺失 + 状态不被训练规划读取。
- **修改位置：** M03（observation events/constraints）、M07（readiness-policy，P4）。**回归测试：** 基线测试 J03 段 + todo。**验收：** §8 J03。

### J04 膝盖疼痛限制动作 — BLOCKED_DOMAIN

- **当前表现（实测 schema）：** 无 `health_observation_events`/`health_constraints` 表（基线测试断言）；疼痛只能落在 exercise notes 文本里，不影响任何计划。
- **正确表现：** pain observation + active constraint；不兼容动作被排除并给替代或休息；限制跨天生效、解除需确认。
- **修改位置：** M03（P2）+ M07/M14（P4）。**回归测试：** 基线测试 J04 断言/todo。**验收：** §8 J04。

### J05 器械占用且不叠加训练量 — BLOCKED_DOMAIN

- **当前表现：** 无器械/可用时间模型、无替代引擎、无组数预算。
- **正确表现：** 替代动作继承未完成组数；该目的 planned sets 不无故增加；解释 retained/lost。
- **修改位置：** M07（substitution-engine/volume-budget，P4）。**回归测试：** J05 todo + property tests。**验收：** §8 J05。

### J06 卧推无胸感检索视频片段 — BLOCKED_DOMAIN

- **当前表现：** 无媒体表；仅 Recipe 有单个 `video_url`。
- **正确表现：** 按问题检索粗人片段、必要时谭成义补充；返回具体起止时间与 cues；记录有效性反馈；不改变主训练量。
- **修改位置：** M08（P5）。**回归测试：** J06 todo。**验收：** §8 J06。

### J07 训练反思改变下一版计划 — BLOCKED_DOMAIN

- **当前表现：** 无 reflection/plan_versions/adjustment proposals；餐单 swap/update 原地改行。
- **正确表现：** 反思产生 proposal→确认→child version；parent 永不覆盖；可回滚。
- **修改位置：** M03（P2）+ M07。**回归测试：** J07 todo（餐单侧已有 `regenerate-supersede.test.ts` 可部分借鉴）。**验收：** §8 J07。

### J08 ASR 识别错误后纠正 — BLOCKED_ENV + BLOCKED_DOMAIN

- **当前表现：** 两个仓库均无 ASR/录音代码（计划审查结论，本次 grep 复核一致）；小米 ASR 封装位置属计划 §23 待确认事项 3。
- **正确表现：** 低置信 preview→一次纠正→commit；错误候选不进正式数据；原始 ASR 保留审计。
- **修改位置：** M09（P6）。**回归测试：** J08 todo。**验收：** §8 J08。

### J09 保存成功但看板未更新 — BLOCKED_DOMAIN

- **当前表现（实测 schema）：** 无 outbox_events/projection_checkpoints/daily_health_state_projection（基线测试断言）；Dashboard 实时拼两个库，无 freshness 概念。
- **正确表现：** write receipt 成功 + outbox pending/failed 可见；看板标 stale；重放无重复。
- **修改位置：** M04（P2）。**回归测试：** J09 断言/todo。**验收：** §8 J09。

### J10 老师发现忽略历史限制 — BLOCKED_ENV

- **当前表现：** pi_harness 未纳入本工作区（用户仅指定两个仓库）；通用 blind reviewer 存在于 pi（计划审查已确认），健康 rubric 不存在。
- **正确表现：** 盲审 state/plan diff/receipts，FAIL 阻止高风险激活；finding 指向缺失 evidence。
- **修改位置：** M12（P7，需 pi_harness 仓库）。**回归测试：** J10 todo。**验收：** §8 J10。

### J11 管理者发现建议长期未执行 — BLOCKED_DOMAIN

- **当前表现：** stats 仅聚合水/运动热量/饮食热量/体重；无建议→接受→执行链；无 policy versions。
- **正确表现：** 聚合含分母/时间窗；只产出 proposal 不改事实。
- **修改位置：** M13（P7）。**回归测试：** J11 todo。**验收：** §8 J11。

### J12 新主体失效切旧 Agent — BLOCKED_ENV

- **当前表现：** 无 health routing/circuit breaker（在 pi_harness 侧）；compass-health 侧无 agent-status 概念。
- **正确表现：** 明示切换 legacy；同一 PostgreSQL；回执标 actor/profile；用户可见备用模式。
- **修改位置：** M11（P3，需 pi_harness 仓库）。**回归测试：** J12 todo。**验收：** §8 J12。

## E2E 脚手架

`backend/tests/e2e/`（本目录同级）提供首个可执行探针：

- `test_service_topology.py` — 验证 M15 缺陷：按 `start.bat` 流程启动时 :8788 不可达（BLOCKED_ENV 跳过即证明）；FastAPI 注册/登录/JWT 闭环（TestClient）可用。

## P0 结论

1. 两仓库在计划审查提交上全部现有测试通过（368+73，加基线 10 条 = 378+73）；无既有红灯，P1 起的任何失败都可归因于新改动。
2. 计划第一部分对现状的所有关键判断（直连 8788、单用户 Display API、硬编码目标、缺失训练/媒体/语音/事件/版本域、start.bat 不启动依赖）均经本次实测复核成立。
3. 环境级障碍已排除并记录：bcrypt 版本钉扎、Docker 引擎启动、既有 PG 容器复用（未重建、未改数据）。
4. 未决阻塞（移交计划 §23）：真实 compass.db 副本与历史取舍、pi_harness 仓库、小米 ASR 封装位置、媒体样本 MP4+SRT。
