# P6 阶段报告 — M09 语音（小米 MiMo ASR）

**执行日期：** 2026-08-24（紧接 P5）
**范围：** M09 的 Agent 可执行部分（provider adapter、意图路由、确认门控提交）。浏览器麦克风 UI 归 M10。

## 一、Provider 验证 [1·实测]

- 接口：`POST https://api.xiaomimimo.com/v1/chat/completions`，model `mimo-v2.5-asr`，base64 音频（data URL），`asr_options.language`
- 密钥：`<LOCAL_SECRET_FILE>` 的 `MIMO_API_KEY`（仅服务端加载，浏览器不可见；值未写入任何仓库/报告）
- **Live 回转测试**：TTS 合成"我今天卧推做了三组，每组八次"→ 转写完全正确
- 实测坑：provider 对 MIME 严格校验（拒绝 `audio/x-wav` 别名）——adapter 已做别名归一

## 二、交付物（compass-health `feat(m09)` + agent `fix(m05)`）

| 模块 | 内容 |
|---|---|
| `services/asr/mimo.py` | 可替换 provider adapter：超时→`AsrUnavailableError`、大小守卫（~10MB 编码上限）、格式归一、错误带 provider 详情 |
| `services/voice_intent.py` | 确定性四类意图分类：查询/记录/修改/反馈。中文数字解析（三组=3、每组八次=8）、含糊措辞检测（"大概/好像"→需确认）、按类别的确认门：**修改计划/疼痛反馈/未知意图一律需确认** |
| `routers/voice_routes.py` | `/api/voice/transcribe`（multipart+JWT）、`/transcribe:text` 文本回退、`/commit` 复用 diet v2 领域命令；领域 needs_confirmation 如实转发候选而非伪装成功；音频默认零保留（`audio_retained: false`） |
| agent `display-server.ts` | 修复 override 提交营养全零缺陷：确认的 items 现在过 `aggregateNutrition` 计算真实宏量 |

## 三、Live 端到端（J08 主链路）✅

```
TTS "我中午吃了一碗牛肉面" → ASR 转写正确 → intent=log_meal(0.85)
→ 领域拒绝："一碗牛肉面" 无法解析 → 返回候选[牛肉1.0, 牛里脊0.95]
→ 用户确认牛里脊200g → commit → PG 落库 214 kcal / 44.4g protein
→ daily-state count=1, status=fresh
```

这正是 J08 的核心验收："错误结果不计入统计；一次低成本纠正完成"。M05 的"拒绝伪精确事实"设计在语音路径下自然生效。

## 四、回归与状态

- compass-health：**97 passed + 1 skip**（+13 voice 测试）
- agent：**403 passed**
- 测试数据已清理；两服务已停

## 五、遗留

1. **麦克风 UI**（M10）：后端 API 就绪，前端接入随 P7。
2. **训练逐组语音**（"卧推三组八次"已能解析出 sets/reps）：commit 到 session 流程待训练页接入后打通（当前返回 unsupported_here 引导到对应页面）。
3. **用户级词典**（§15.5 动作别名/食物本地名）：结构已留（intent entities），积累真实误识别数据后再建。
