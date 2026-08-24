# P5 阶段报告 — M08 视频/SRT 资料库

**执行日期：** 2026-08-24（紧接 P4）
**范围：** M08 全部 Agent 可执行部分。老师/管理者审查层按用户指示暂缓。

## 一、真实资料盘点结果 [1·代码/实测]

**12 个视频全部可读**（ffprobe 成功），与 Downloads 下 12 个 SRT 完成配对：

| 资产 | 配对 | 完整性 |
|---|---|---|
| 凯圣王三分化①训练计划 (21.5min) | 凯圣王-谭(3).srt | complete |
| 凯圣王三分化②跟练胸肩三头 (84.2min) | 凯圣王-谭.srt | complete |
| 凯圣王三分化④跟练背肩后束二头 (84.1min) | 凯圣王-谭(1).srt | complete |
| 凯圣王三分化⑤跟练腿 (58.1min) | 凯圣王-谭(2).srt | complete |
| 粗人卧推私教课 (48.7min) | 粗人(力量矩阵营养学.srt | complete |
| 谭成义 手臂教学二期 (38.7min) | 私教系列之手.srt | **subtitle_truncated**（SRT 止于 31:05，缺 ~7.6min） |
| 谭成义 手臂训练二 (13.6min) | 私教系列之手第二部分.srt | complete |
| 谭成义 肩部教学 (39.8min) | 私教系列之肩.srt | complete |
| 谭成义 胸部教学 (38.4min) | 私教系列之胸.srt | **subtitle_truncated**（SRT 止于 34:08，缺 ~4.3min） |
| 谭成义 腹肌教学 (16.8min) | 私教系列之腹.srt | complete |
| 谭成义 腿部训练 (52.9min) | 私教系列之腿.srt | complete |
| 谭成义 背部跟练 (49.2min) | 私教系列之背.srt | complete |

凯圣王四个模糊命名的 SRT 通过时长邻近匹配确认配对（gap≈0s），已写入 manifest 作为 confirmed mapping——计划 §13.1 预判的三类问题中两类实测命中（截断），"名词解释/Vlog 缺失"实际不存在（12 视频全可读）。

## 二、交付物（compress_health_agent，提交 `4e1786d`）

- **schema**：media_assets（内容哈希唯一）、media_pairings（完整性 + 可用窗口）、video_segments（draft→confirmed、source role）、segment_feedback
- **导入器**：SHA-256 校验、ffprobe 时长、SRT 解析（CRLF/BOM 兼容）、manifest 配对、完整性规则（complete / subtitle_truncated→可用窗口=字幕终点 / missing_subtitle / video_decode_error）；幂等重导
- **检索**：确定性过滤优先（可用窗口在 SQL 层强制、模式/部位/类别/文本），每条结果带 completeness 与 sourceRole——截断来源不可能被当成完整依据；helpful/not-helpful 计数
- **端点**：`GET /api/v1/media/segments:search`、`POST /api/v1/media/segments:feedback`（经 BFF 即 `/api/domain/v1/media/*`）
- **批量导入脚本**：`src/media/run-import.ts`（幂等，环境变量可改目录）

## 三、验证

- 测试：agent **403 passed**（+4 媒体不变量：SRT 解析、截断窗口、缺失字幕、幂等重导+检索元数据）
- Live 批量导入：**12/12 成功**，10 complete + 2 truncated；**183 个草稿片段**入索引
- Live 检索：中文关键词（"胸""肩膀"）命中并返回 trainer/sourceRole/completeness/时间区间/localPath

## 四、J06 状态与剩余

J06（卧推无胸感检索）的检索面已完成：`?text=胸&category=correction` 会优先返回粗人的修正类片段（sourceRole=chest_specialist），且检索结果天然不携带训练量语义——M07 已保证辅助资料不会自动加组。剩余为人工确认草稿片段的标题/标签（confirmed 段落重索引时保留），属日常运营而非开发阻塞。
