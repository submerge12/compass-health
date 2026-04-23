# Compass Health

Compass Health 是一个使用 FastAPI、原生 JavaScript 和 SQLite 构建的双语 AI 配餐与健康管理系统。

它不是简单的聊天式 Demo，而是围绕真实用户流程设计的完整闭环系统：

1. 收集健康档案与饮食约束
2. 审计用户食物库是否营养闭环可行
3. 生成候选菜池
4. 排布一周餐单
5. 生成采购清单
6. 基于真实执行数据做日反馈和周复盘

## 项目能力

- 基于 BMR 的健康档案与热量目标计算
- 饮食偏好与固定餐管理
- 基于结构化食材库的闭环营养审计
- 从早餐池和午晚餐共享主菜池生成一周餐单
- 从已落库计划自动聚合采购清单
- 基于真实饮食与运动记录生成每日/每周反馈
- 中英文双语界面与双语 API 返回

## 为什么这个项目值得展示

这个项目的核心不是“让 LLM 直接生成所有东西”，而是采用了混合架构：

- 核心营养审计、目标计算、周排餐、采购聚合都走 deterministic engine
- LLM 只负责软任务，比如自由文本偏好分类、菜名生成、做法语言化
- 上下文记忆依赖结构化数据库状态，而不是简单把历史对话拼进 prompt
- 项目是本地真实可运行的前后端系统，带数据库、日志和测试

## 系统流程

### 输入

- 用户画像：年龄、性别、身高、体重、目标体重、减脂目标
- 用户约束：食物偏好、固定餐、已保存菜谱
- 用户行为：饮食记录、运动记录、饮水记录、身体状态
- 当前配餐输入：早餐池和主菜池的选择结果

### 处理

- `services/nutrition_audit.py`：检查食物库闭环可行性与微量元素覆盖
- `services/planning_context.py`：组装每天的结构化 planning context，并应用优先级规则
- `services/menu_planner.py`：生成候选菜池并安排周计划
- `services/recipe_suggester.py`：调用 LLM 给菜品草案命名或补充可读做法
- `services/procurement.py`：从已落库的计划聚合采购清单
- `services/feedback_loop.py`：生成每日和每周执行反馈

### 输出

- 候选菜池
- 一周安排好的餐单
- 采购清单
- 每日执行反馈
- 每周复盘与调整建议

## 架构概览

```text
前端（原生 JS SPA）
  -> api.js
  -> FastAPI routers
  -> service layer
  -> SQLite

LLM 层
  -> DeepSeek API
  -> 偏好分类
  -> 菜品命名 / 做法语言生成

确定性核心
  -> 热量目标
  -> planning context
  -> nutrition audit
  -> weekly arrangement
  -> procurement
  -> feedback loop
```

## 技术栈

- 后端：FastAPI、SQLAlchemy、APScheduler
- 前端：vanilla JavaScript、HTML、CSS
- 数据库：SQLite
- LLM API：DeepSeek（OpenAI 兼容调用方式）
- 认证：JWT access token + refresh token
- 测试：pytest

## 核心工程设计

### 1. 受控式工具编排，而不是开放式 Agent 自由决策

这个系统不是把“调用什么工具”全交给模型，而是由工程流程明确约束：

- 先审计
- 再生成候选池
- 需要自然语言包装时再命名
- 用户选择后再安排周计划
- 最后再聚合采购清单

这样核心营养逻辑更可控、可测、可解释。

### 2. 结构化 memory，而不是简单拼接聊天历史

系统的主要 memory 是落在数据库里的结构化状态：

- 用户画像
- 用户设置
- 饮食偏好
- 固定餐
- 已保存菜谱
- 饮食 / 运动 / 身体状态历史
- 已生成计划

`planning_context.py` 会把这些状态组装成 day-level context，并应用优先级链：

`recorded > fixed > recipe > generated`

### 3. 有边界的 LLM 使用

LLM 被限制在以下任务中：

- 把自由文本饮食偏好映射成标准 slug
- 给候选菜品草案起名
- 生成对用户更友好的做法说明

真正的营养与计划决策都保留在本地逻辑里。

## 本地运行

### 方式 A

双击：

- `start.bat`

会自动启动前后端并打开浏览器。

### 方式 B

后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

前端：

```bash
cd frontend
python -m http.server 5500
```

### 本地地址

- App: [http://localhost:5500](http://localhost:5500)
- API: [http://localhost:8000](http://localhost:8000)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## 环境变量

使用 `backend/.env.example` 复制出 `backend/.env`。

主要变量有：

- `SECRET_KEY`
- `ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_DAYS`
- `DATABASE_URL`
- `DEEPSEEK_API_KEY`
- `LOG_DIR`
- `ALLOW_WEAK_SECRET`
- `TRUST_PROXY`

## 项目结构

```text
compass-health/
├─ backend/
│  ├─ main.py
│  ├─ auth.py
│  ├─ database.py
│  ├─ models.py
│  ├─ middleware.py
│  ├─ logging_config.py
│  ├─ routers/
│  ├─ services/
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/
│  ├─ index.html
│  ├─ css/
│  └─ js/
├─ start.bat
├─ stop.bat
└─ README.md
```

## 当前部署状态

当前这个仓库展示的是一个真实可运行的本地系统：

- FastAPI 本地运行在 `8000`
- 前端静态服务本地运行在 `5500`
- 默认数据库是本地 SQLite

目前仓库里还没有整理成云部署模板。

## 面试展示建议

如果你想把这个项目放进简历或面试，最值得强调的点是：

- 混合 AI 架构：deterministic planning + bounded LLM
- 结构化上下文记忆：基于用户状态和 planning context
- 真实可运行，而不是 prompt demo
- service layer 拆分清晰：audit / planner / procurement / feedback
- 面向用户的韧性设计：额度、日志、告警、失败回退

## 注意事项

- 不要提交 `backend/.env`
- 不要提交 `backend/compass.db`
- 不要提交 `backend/logs/` 和本地备份文件

