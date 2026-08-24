# P4 阶段报告 — M06/M07 结构化训练域

**执行日期：** 2026-08-24（紧接 P3）
**范围：** §20 P4 的 M06（训练域/三分化/逐组记录）与 M07（自适应循环基础/替代引擎/反思→版本）。readiness-policy 完整规则引擎与真实多循环验证留待真实使用期（计划 §21 P4 完成条件中"至少两个真实循环仅 shadow 调整"需要时间维度）。

## 一、交付物（compress_health_agent，3 提交）

| 提交 | 内容 |
|---|---|
| `edd03d0` | M06：训练域 7 张表（exercise_definitions/substitutions/templates/sessions/session_exercises/set_logs/reflections）；三分化 A/B/C 参考计划作为**可版本化种子数据**（含 alternates 与默认循环模式，非硬编码规则）；training-service（一次性播种、prepareSession 约束过滤、session 状态机、逐组幂等记录、read-back 恢复）；4 条 DB 不变量测试 |
| `4a86cff` | M07：substitution-engine（确定性候选 + retained/lost 解释 + **不叠量硬不变量**）；reflection-engine（结构化反思 → child DRAFT version → 原子激活，parent 内容永不改动）；display-server 11 条训练 v1 路由；2 条 DB 不变量测试 |

## 二、验收门状态（§19.2）

| Journey | 状态 | 证据 |
|---|---|---|
| J02 逐组训练 | ✅ | 测试：状态机拒绝非法转换、幂等键重试返回原行且忽略噪声 payload、未知 load/RIR 保持 null；live：30kg×10 落库、无重量组保持 null、read-back 完整 |
| J04 膝痛限制 | ✅ | 测试：block 约束把 single_leg_squat 从 C 日提案中剔除并给出原因，其余动作保持 as_planned |
| J05 器械占用不叠量 | ✅ | 测试 + live：完成 2/3 组后替代，replacement.targetSets=剩余 1 组，原行已完成组保留为 actual，目的总量 3 不变；决策事件入 user_decision_events |
| J07 反思改下一版 | ✅ | 测试 + live：反思→child draft（parent active 不变、contentJson 相等）→激活后 child active/parent superseded/指针切换/反思记录 acceptedAt；重复 propose 幂等 |

## 三、关键设计事实

1. **替代预算在 apply 事务内二次校验**：propose 与 apply 之间若剩余组数变化（并发记录了一组），apply 抛错要求重新 propose——防止陈旧提案叠量。
2. **幂等双层**：显式 idempotencyKey + (sessionExerciseId, setNumber) 唯一约束 upsert；无键重试同一组号也安全。
3. **激活保护**：拒绝激活无 parent 的根版本——初始模板只能被 child 替换，不能被"直接激活"绕过审查。
4. 训练完成后投影重建（finish 路由同步 persistDailyProjection），daily state 的 exerciseMinutes 随粗摘要可见。

## 四、回归

agent：**399 passed**（+2 M07 不变量；M06 批次时为 397）。
compass-health 侧无新改动（训练端点经既有 BFF 通用代理可达，合同已由 M01 测试覆盖路径模式）。

## 五、遗留

1. readiness-policy（睡眠/疲劳/疼痛→缩量/休息 proposal 的完整规则引擎）：数据面已就绪（observations + constraints + prepareSession 过滤），规则编排属 M07 收尾，建议在真实使用 1-2 个循环后按数据调参。
2. 训练 UI（M10）：后端 v1 全部就绪，前端页面接入随 P7。
3. pi_harness（M11/M12）与媒体库（M08/P5）仍 BLOCKED_ENV / 待样本。

**下一步建议：P5 视频/SRT（M08）需要代表性 MP4+SRT 样本；若暂无样本，可先做 M14 收尾（确认矩阵完整测试）或 M10 前端接入。**
