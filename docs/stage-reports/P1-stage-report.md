# P1 阶段报告 — M01 身份与 BFF + M15 启动基础

**执行日期：** 2026-08-24（紧接 P0，同一工作区）
**范围：** §20 P1 中的 M01（核心）与 M15（基础）。M02 的 SQLite 迁移部分仍被"真实 compass.db 副本"阻塞（§23 待确认 1），但 P1 期间的一次实测发现了影响 M02 的新事实（见 §四）。

## 一、M01 完成情况

### compress_health_agent（提交基线 1c73205 之上，未提交工作区改动）

| 文件 | 改动 |
|---|---|
| `src/server/display-server.ts` | ① `DisplayServerOptions.resolveUserId`：服务令牌模式下按 `X-External-User-ID` 每请求解析内部用户（未配置令牌时拒绝该头，localhost-trusted 模式保持单用户）；② 回显入站 `X-Request-ID`；③ CORS 允许头补齐 `X-External-User-ID/X-Request-ID/X-Journey-ID` |
| `src/server/serve.ts` | 服务令牌模式自动装配 `resolveUserId`（`repo.findOrCreateUser`，locale/timezone 沿用环境配置），启动日志区分两种模式 |
| `tests/server/display-server.test.ts` | 新增 4 条身份合同测试（解析、无服务鉴权拒绝、request-id 回显、解析后作用域进 handler） |

### compass-health（提交基线 b1716fa 之上，未提交工作区改动）

| 文件 | 改动 |
|---|---|
| `backend/services/domain_identity.py`（新增） | `external_id_for_user`：`compass-health:{id}`，基于不可变数字 id（§18.1 步骤 3） |
| `backend/services/health_domain_client.py`（新增） | httpx 客户端：服务令牌 + `X-External-User-ID` + `X-Request-ID/X-Journey-ID` 传播；`trust_env=False`（本机私有服务不走系统代理——实测中代理会拦截 127.0.0.1）；超时→`DomainUnavailableError` |
| `backend/routers/health_domain_routes.py`（新增） | `/api/domain/*` 认证代理：JWT 必须；external id **只**来自已验证 JWT（客户端伪造头被忽略）；`HEALTH_DOMAIN_MODE≠postgres` 或领域不可达 → 503 `domain_unavailable` + request id，**绝不回退 SQLite 写** |
| `backend/main.py` | 注册路由；新增 `/healthz`（M15 live 探针，无认证无数据） |
| `frontend/js/api.js` | `_agentRequest` 默认改走 `${API_BASE}/api/domain/*`（JWT + trace headers + 401 自动刷新沿用）；`ch_display_api_mode=direct` 保留为开发直连回退；错误信息带 request id |
| `backend/tests/test_health_domain_bff.py`（新增） | 7 条合同测试：401、JWT 身份与 trace 传播、伪造 external id 被忽略、双用户隔离、POST body 转发、领域宕机 503、模式关闭 503（httpx.MockTransport，无需真实 :8788） |
| `backend/tests/e2e/test_service_topology.py` | P0 探针更新：断言前端默认模式为 `bff`（M01 验收不变量固化） |
| `scripts/start-health-system.ps1`（新增） | M15：一键按序启动 PG→领域 API→FastAPI→前端，每级健康检查通过才宣布下一级；不覆盖用户 backend/.env 的 SECRET_KEY；探测走无代理 HttpClient（系统代理会劫持 localhost） |

## 二、验证结果

**测试（全绿）：**
- agent：**382 passed**（368 原有 + 10 旅程基线 + 4 身份数）
- compass-health：**82 passed + 1 skipped(BLOCKED_ENV)**（73 原有 + 7 BFF + 2 e2e）
- agent typecheck 通过

**真实链路（两次实测，浏览器式调用全程无 8788 直连）：**
1. 注册/登录（SQLite JWT）→ `GET /api/domain/health` → BFF 派生 `compass-health:1` → 领域 find-or-create 内部用户 → 返回该用户 UUID ✓
2. `GET /api/domain/plan` → 返回新用户空计划，**<local-user-id> 的 84/54 条计划不可见**（隔离成立）✓
3. 无 JWT → 401；领域停机 → 503 `domain_unavailable` + request id ✓
4. M15 脚本一键拉起四级栈，全部 `[OK]`，并在脚本栈上复验了 ①②③ ✓

**验收对照（M01 计划行）：**
- "100% 浏览器健康请求经过 BFF"：默认模式改为 bff，直连需显式 localStorage 开发开关 ✓（新 e2e 断言固化）
- "同一 journey id 前端错误/FastAPI 日志/领域回执关联"：前端生成并携带、BFF 传播、领域回显 request id ✓（跨 FastAPI 日志与领域的全自动关联在 M04 事件表中落库）
- "跨用户访问 403/404"：外部 id 派生自 JWT，伪造头被忽略，双用户隔离测试通过 ✓
- "Domain API 不可用 503 + request id，不回退 SQLite"：测试固化 ✓
- 旧 Agent 影响：localhost-trusted 模式（无令牌）行为完全不变 ✓

## 三、M15 完成情况（基础）

`start-health-system.ps1` 实测通过；`/healthz` 已加（live）；ready 语义 = `/api/domain/health`（M04 补 `/readyz`/`/projection-health`）。原 `start.bat` 未动，作为 legacy 回退（§18.3）。

## 四、影响 M02 的新发现 [1·代码/实测]

**PostgreSQL `compass_health` 库内存在两套 schema，真实历史分散于两侧：**

| | `public.*`（docker/init.sql 建） | `compass_health.*`（drizzle db:push 建，当前代码实际读写） |
|---|---|---|
| users | 1（<local-user-id>） | 6（<local-user-id>、default-user、aoh-p3-diagnostic、pi-e2e×2、pi-dislike） |
| meal_plan_entries | **84** | **54** |
| diet_logs | 5 | 4 |

即：**"权威源分裂"不止 SQLite vs PostgreSQL，还有 PG 内 public vs compass_health**。M02 迁移设计必须把"PG 内 schema 归一"并入 §18.1 幂等导入与对账；<local-user-id> 在两侧的计划/记录需要按日期去重合并（§23 待确认 2 的答案的一部分：两侧都有独有真实记录）。P0 报告 §四的盘点数字当时只统计了 public schema，特此修正——两套数字均如上表。

## 五、遗留与移交

1. **M02 主体仍待用户输入**：真实 compass.db 副本（SQLite 侧行数/日期范围）→ 才能定三方（public/ch/SQLite）合并策略。
2. pi_harness 未纳入：M11 fallback 路由（J12）无法在本工作区验证。
3. 本次改动均未提交（两仓库 `git status` 可审）；确认后建议按仓库分别提交（agent：display-server 身份 + 测试；compass：BFF + 前端 + 启动脚本 + 测试）。
4. 环境注记：本机系统代理会劫持 localhost HTTP（pip SSL 报错、PowerShell Invoke-WebRequest、httpx 默认 trust_env 均中招）——client 已 `trust_env=False`、脚本已用无代理 HttpClient，后续新组件需沿用此约定。
