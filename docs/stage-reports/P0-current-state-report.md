# P0 基线与冻结 — Current-State 报告

**执行日期：** 2026-08-24
**依据：** 《健康系统基于现有代码的修改计划》§20 阶段 P0 / §21 P0 进入与完成条件 / M00 工作包
**工作区：** `G:\new agent`（compress_health_agent + compass-health 两个克隆仓库）

## 一、进入条件核对（§21 P0）

| 进入条件 | 结果 |
|---|---|
| GitHub commit/本地 branch 明确 | ✅ 两仓库 HEAD 与计划审查提交完全一致（见下） |
| 能只读访问两库 | ✅ 公开仓库克隆成功 |
| 不修改正式数据 | ✅ 真实用户 `<local-user-id>` 数据零改动；旅程测试使用独立用户 `journey-baseline-user` 且用后清理；PG 容器仅 `docker start` 未重建 |

## 二、固定版本

| 仓库 | 提交 | 时间 | 与计划审查版本一致 |
|---|---|---|---|
| compress_health_agent | `main@1c73205b48673efc0b24c8735e68f0dd2a7abf7f` | 2026-07-20 | ✅ |
| compass-health | `main@b1716fa50f529cfe63657f4c3469fadb8e2d8f20` | 2026-07-06 | ✅ |
| pi_harness | 未克隆（用户未提供；J10/J12/M11/M12 相关验证 BLOCKED_ENV） | — | — |

## 三、现有测试真实运行结果（P0 核心要求）

| 套件 | 命令 | 结果 |
|---|---|---|
| agent（无 DB） | `pnpm test` | 333 passed / 35 skipped（skip=DB 集成） |
| agent（PostgreSQL :5433 实例） | `DATABASE_URL=… pnpm test` | **368 passed / 0 failed** |
| agent（含本次新增旅程基线） | 同上 | **378 passed / 0 failed**（新增 `tests/acceptance/continuous-health-journeys.test.ts`：10 特征测试 + 11 todo 占位） |
| compass-health | `.venv python -m pytest backend/tests` | 先 56 failed（**全部**为 bcrypt 5.x ↔ passlib 1.7.4 环境不兼容）；钉 `bcrypt==4.0.1` 后 **73 passed**；加 e2e 探针后 **75 passed / 1 skipped(BLOCKED_ENV)** |

**结论：两个仓库在审查提交上无任何真实红灯。** P1 起的任何测试失败可归因于新改动，不会被既有失败干扰。

环境级修复（仅本机 venv/容器，未改两仓库生产代码）：
1. `compass-health/.venv` 钉 `bcrypt==4.0.1`（建议后续在 `backend/requirements.txt` 加上限 `bcrypt<4.1`，属 P1 顺手项，本次未改仓库文件）。
2. pip 走系统代理时 SSL 报错 `check_hostname requires server_hostname`；用 `--proxy=""` + curl 下载 wheel 解决。
3. Docker Desktop 引擎启动；发现既有容器 `compass-health-pg`（pgvector:pg17, :5433, 卷 `compass-health-agent_pgdata`）→ 复用启动，未删除未重建。

## 四、双库盘点（§18.1 步骤 1 的可执行部分）

**PostgreSQL `compass_health`（⚠️ 更正：库内有两套 schema，P1 期间实测发现，两套都有真实数据）：**

| | `public.*`（docker/init.sql 建） | `compass_health.*`（drizzle db:push 建，**当前 agent 代码实际读写**） |
|---|---|---|
| users | 1（`<local-user-id>`, tz Asia/Shanghai, created 2026-06-17） | 6（<local-user-id>、default-user、aoh-p3-diagnostic、pi-e2e×2、pi-dislike） |
| meal_plan_entries | 84（2026-06-18..24） | 54 |
| diet_logs | 5（2026-06-17） | 4 |

food_items 目录（20MB dump 主体）在 public schema。表清单含 cooking_records、daily_activity_plans、meal_compositions、natural_units、food_aliases、user_dishes、user_seasoning_preferences、seasonings——无任何 training/outbox/projection/version/observation 表（与计划 §1 判断一致，已由基线测试固化为断言）。本节初版只统计了 public schema（psql 默认 search_path），特此更正；schema 归一需并入 M02 迁移设计。

**回滚快照（§18.1 步骤 2）：** `p0-artifacts/compass_health_pg_snapshot_2026-08-24.sql`（pg_dump，SHA-256 `d6825204ebfa339024f80688598c9899d1b3917d679e2f043ee018355998ae2d`）。

**SQLite：** 无本地 compass.db 副本 → **BLOCKED_ENV**。真实历史取舍（§23 待确认事项 2）待用户提供原工作目录或只读 dump。

## 五、J01–J12 当前行为证据

落地位置：`compass-health/docs/health-journeys/README.md`（12 条全量注册表：场景/输入/当前表现/正确表现/根因阶段/修改位置/回归测试/验收标准）。

可执行证据：
- `compress_health_agent/tests/acceptance/continuous-health-journeys.test.ts` — schema 缺口断言（无幂等/置信/修正链列、无训练/事件/投影表）+ live 特征探针（J01 闭环成立、**重复提交产生重复事实**、汇总硬编码 2000ml/30min、身体状态仅有 weight 入口）。
- `compass-health/backend/tests/e2e/test_service_topology.py` — auth 闭环 PASSED；`AGENT_API_BASE` 直连 8788 断言 PASSED（M01 缺陷固化）；按 start.bat 流程探测 :8788 → **SKIPPED(BLOCKED_ENV)**，skip 理由即 M15 缺陷记录。

对计划"当前问题"判断的复核：全部成立，无一被证伪（含 api.js:645、start.bat 范围、serve.ts 单用户、display-server 可选 Bearer、handleDailySummary 硬编码）。

## 六、§21 P0 完成条件核对

| 完成条件 | 状态 |
|---|---|
| 现有测试真实运行结果已记录 | ✅ 本文 §三 |
| J01–J12 当前行为有证据 | ✅ 注册表 + 2 个可执行探针文件（J02-J08/J10/J11 为 BLOCKED_DOMAIN 占位，J08/J10/J12 含 BLOCKED_ENV 成分） |
| 双库表/用户/日期范围已盘点 | ✅ PG 完成；SQLite BLOCKED_ENV（无副本） |
| 备份可恢复 | ✅ pg_dump 快照 + 校验和（恢复演练属 P1 迁移前置，未执行破坏性验证） |
| 所有结论仍按 1–5 证据分级 | ✅ 注册表沿用 [1·代码]/[2·测试]/[3·需求]/[4·推断]/[5·待确认] 标注惯例 |

## 七、移交给用户的待决事项（影响 P1 范围，§23）

1. **真实 compass.db**：提供原工作目录路径或只读 dump → M02 迁移与身份映射才能进入实施。
2. **pi_harness 仓库**：是否纳入本工作区 → M11/M12 与 J10/J12 的前置。
3. **小米 ASR 封装位置**（P6 前需确认，不阻塞 P1）。
4. 生产身份范围（单/多用户）——P1 的 BFF 用户映射设计默认按"多用户映射架构、单账户使用"推进，如无异议 P1 按此执行。

## 八、产物清单与仓库状态

```
G:\new agent\
├── compress_health_agent\   （clone @1c73205b；未提交改动：tests/acceptance/continuous-health-journeys.test.ts 新增）
├── compass-health\          （clone @b1716fa；未提交改动：docs/health-journeys/README.md、backend/tests/e2e/ 新增）
├── p0-artifacts\
│   └── compass_health_pg_snapshot_2026-08-24.sql   （回滚快照，SHA-256 d6825204…）
└── P0-current-state-report.md   （本文件）
```

两仓库按规则保持未提交状态（用户未要求 commit）；改动均为纯新增文件，`git status` 可审。

## 九、P1 进入建议

P0 出口条件满足（除 SQLite 侧 BLOCKED_ENV，已按 M00 规则登记而不计为业务失败）。P1 按 §20 执行 **M01（BFF/停止直连 8788）+ M02（SSOT/导入器）+ M15 基础（统一启动）**，其中 M02 的 SQLite 迁移部分以待决事项 1 解锁为前提，可先行实施 PG 侧 schema 兼容与 importer 骨架。
