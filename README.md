# Compass Health

[中文说明](./README.zh-CN.md) | [English](./README.en.md)

Compass Health 是一个双语的 AI 配餐与健康管理系统，使用 FastAPI、原生 JavaScript 和 SQLite 构建。它不是单纯的聊天 Demo，而是一个可本地运行的完整前后端项目：从健康档案、饮食偏好、固定餐，到候选菜池、一周餐单、采购清单和执行反馈，都有完整闭环。

Compass Health is a bilingual AI-assisted meal planning and health tracking system built with FastAPI, vanilla JavaScript, and SQLite. It is not just a chat demo. It is a runnable full-stack product with a complete loop from health profile and food preferences to candidate dishes, weekly plans, shopping lists, and execution feedback.

## Highlights

- 混合架构：核心营养审计、周排餐、采购聚合走 deterministic engine，LLM 只用于偏好分类和菜名生成
- 结构化记忆：基于用户画像、固定餐、饮食记录、历史计划构建 planning context，而不是简单拼接对话历史
- 真实可运行：本地 FastAPI + 前端静态服务 + SQLite，支持 API 文档、日志和测试
- 工程化拆分：审计、规划、命名、采购、反馈分别封装在独立 service 中

- Hybrid architecture: deterministic planning for nutrition, arrangement, and procurement, with LLM usage limited to soft tasks
- Structured memory: planning context is assembled from persisted user state rather than raw prompt history
- Truly runnable: local FastAPI backend, static frontend, SQLite database, API docs, logs, and tests
- Service-oriented engineering: audit, planning, naming, procurement, and feedback are separated into focused modules

## Quick Links

- 中文完整版：[README.zh-CN.md](./README.zh-CN.md)
- English full version: [README.en.md](./README.en.md)

## Local Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

```bash
cd frontend
python -m http.server 5500
```

- App: [http://localhost:5500](http://localhost:5500)
- API: [http://localhost:8000](http://localhost:8000)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

