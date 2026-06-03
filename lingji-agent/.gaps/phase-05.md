# Phase 5 缺口记录

**日期**: 2026-05-31
**阶段**: 认知层（LangGraph 状态机实现 + Phase 4 联动消除自欺欺人）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| agent_think 接入真实 LLM 调用 | ✅ 通过 RunnableConfig 注入 |
| 条件路由（tool_calls → executor, content → reply） | ✅ |
| tool_executor 工具调度 + 结果回写 | ✅ |
| format_response 提取 + fallback | ✅ |
| MAX_TOOL_ROUNDS 防无限循环 | ✅ 5 轮上限 |
| **反自欺专项测试** | ✅ **4/4** |
| **pytest 全量** | ✅ **61/61 passed** |

## 反自欺验证清单

| 测试 | 验证内容 | 结果 |
|------|----------|------|
| test_agent_think_calls_llm | LLM 被真实调用，非透传 | ✅ |
| test_different_inputs_different_calls | 不同输入产生不同调用 | ✅ |
| test_llm_error_propagates | 异常不静默吞掉 | ✅ |
| test_empty_content_without_tools_is_detected | 空回复有日志 | ✅ |

## 实现详情

### orchestrator.py — 认知层状态机

```
agent_think                          tool_executor
   │                                     │
   │ LLM 调用                             │ 执行工具
   │ 解析 tool_calls / content           │ 追加 tool 消息
   │                                     │
   ├─ 有 tool_calls ──→ tool_executor ──┤
   │                                     │
   │                        轮次<5? ──→ agent_think (循环)
   │                        轮次≥5? ──→ format_response
   │                                     │
   └─ 无 tool_calls ──→ format_response │
                         │               │
                         提取最终文本
```

### 关键设计

- **LLM 注入**: `RunnableConfig.configurable._connector`（LangGraph 标准模式）
- **工具注入**: `RunnableConfig.configurable._registry`
- **防循环**: MAX_TOOL_ROUNDS=5，超限强制结束
- **错误传播**: LLM 失败 → final_response="❌ 错误信息"（不抛异常）
- **消息历史**: 每次 LLM 调用和工具执行都追加到 messages

### main.py — 完整闭环

```
CMD_TEXT 到达 → PromptManager.build_system_prompt()
              → run_agent(graph, user_text, system_prompt)
              → LLM 推理 → 工具执行 → 最终回复
              → AGENT_RES 发送回手机
```

## Phase 4-5 联动结果

| 联动点 | 状态 |
|--------|------|
| ILLMConnector → agent_think | ✅ 通过 configurable 注入 |
| ToolRegistry → tool_executor | ✅ 通过 configurable 注入 |
| PromptManager → run_agent | ✅ system_prompt 参数传入 |
| create_connector → build_graph | ✅ main.py 组装 |

---

## 新缺口

无。
