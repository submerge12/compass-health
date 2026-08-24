# P7 阶段报告 — M10 前端接入（语音助手页）

**执行日期：** 2026-08-24（紧接 P6）
**范围：** M10 中价值最高的一块——把 P3/P4/P6 已就绪的后端 API 接入真实用户界面。老师/管理者部分按指示继续跳过。

## 一、交付物（compass-health `e052ccf`）

- **`frontend/js/api.js`**：`voiceTranscribe`（multipart 经认证 BFF + trace 头）、`voiceTranscribeText` 文本回退、`voiceCommit`、`getDailyState`
- **`frontend/js/pages/voice.js`**（新页面）：
  - 按住说话（MediaRecorder），松开即转写
  - 转写结果展示：意图类别徽章（查询/记录/修改/反馈/未知）+ 动作名 + 置信度
  - **确认按钮由后端意图策略驱动**：疼痛/修改/未知一律显示"确认并保存+放弃"，干净记录直接"保存"
  - 回执面板：已保存 / 需确认候选列表（来自领域 needs_confirmation）/ 拒绝提示
  - **文本输入回退常驻**——ASR 关闭或不可用时页面完整可用（M09 回滚要求）
- 导航栏新增"语音"入口；页面注册进 app.js 与 index.html

## 二、浏览器 GUI 黑盒验证 ✅（web-gui-tester 流程，真实栈）

启动完整系统（PG :5433 + 领域 :8788 服务鉴权模式 + FastAPI :8000 带 MIMO key + 前端 :5500），在真实浏览器中走完：

1. 注册新用户 → BMR 引导三步（年龄/性别→身高体重→目标）→ 进入主应用
2. 主导航出现**"语音"入口**，点击进入语音助手页
3. 输入"今天膝盖疼" → 显示 `反馈 / report_pain / confidence 85%` + 确认门控按钮 ✅
4. 点击确认 → 回执"✅ 已保存" → **PostgreSQL 中出现 pain observation**（bodyPart=膝盖）✅
5. 输入"帮我订机票" → `未知 / confidence 20%` + "请换种说法"，**无任何写入路径** ✅

验证中发现并修复：非饮食类提交的回执误显示"log undefined, ? kcal"（现按类型区分文案）。测试数据已清理，全部服务已停。

## 三、回归

- compass-health：**97 passed + 1 skip**

## 四、整体进度对照（§20）

| 阶段 | 状态 |
|---|---|
| P0–P6 | ✅ 全部完成并分阶段提交 |
| P7 | ◐ 语音页完成；剩余为仪表盘 daily-state 卡片美化、训练逐组页、媒体检索 UI |
| P8 | 待多循环真实使用后评估 |

**剩余工作均不阻塞真实使用**：用户现在可以通过页面完成注册→语音记录饮食→纠正→疼痛反馈的完整闭环。训练逐组记录与媒体检索已有完整 REST API（`/api/domain/v1/training/*`、`/api/domain/v1/media/*`），UI 可渐进补充。
