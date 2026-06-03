# Phase 4 缺口记录

**日期**: 2026-05-31
**阶段**: LLM 抽象层（ILLMConnector + DeepSeekImpl + PromptManager + LangGraph 验证）

## 验证结果

| 检查项 | 结果 |
|--------|------|
| DeepSeekConnector 重试 + 错误处理 | ✅ 指数退避 3 次 |
| OllamaConnector 预留骨架 | ✅ NotImplementedError 明确提示 |
| create_connector() factory | ✅ 根据 provider 字段自动选择 |
| PromptManager 工具 schema 注入 | ✅ 风险图标 + JSON 约束 |
| LangGraph 编译 | ✅ CompiledStateGraph |
| **pytest 全量** | ✅ **51/51 passed** |

## 测试分布

| 模块 | 新增 | 累计 |
|------|------|------|
| llm_provider | 9 | — |
| prompt_manager | 6 | — |
| orchestrator | 4 | — |
| config | — | 9 |
| db | — | 4 |
| protocol | — | 3 |
| registry | — | 4 |
| ws_client | — | 9 |
| **合计** | **19** | **51** |

## 实现详情

### llm_provider.py — DeepSeekConnector
```
- 延迟初始化 AsyncOpenAI（复用连接）
- 指数退避重试: 1s → 2s → 4s（最多 3 次）
- 统一返回格式: {content, tool_calls, model, usage}
- tool_calls 标准化为 dict 列表
```

### llm_provider.py — Factory
```
create_connector(config) → ILLMConnector
  provider="deepseek" → DeepSeekConnector
  provider="ollama"  → OllamaConnector
```

### prompt_manager.py — PromptManager
```
- BASE_SYSTEM_PROMPT: 角色 + 规则 + 环境信息
- TOOL_CALLING_INSTRUCTION: 工具列表 + 风险图标 (🟢🟡🔴)
- build_system_prompt(): 完整 System Prompt
- build_messages(): system + history + user
```

### orchestrator.py — LangGraph
```
- 4 节点状态机编译通过
- graph.invoke() 可正常执行
- Phase 5 将实现 agent_think + format_response
```

---

## 新缺口

无。
