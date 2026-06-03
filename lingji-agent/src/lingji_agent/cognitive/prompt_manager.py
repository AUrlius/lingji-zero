"""System Prompt 模板管理

支持：
- 基础系统提示
- 工具调用 schema 注入
- Function Calling JSON 格式约束
"""

from lingji_agent.execution.registry import ToolRegistry


BASE_SYSTEM_PROMPT = """你是灵机助手，运行在用户的个人电脑上。你可以访问文件系统并执行安全的系统操作。

## 核心规则
1. 始终用中文回复
2. 危险操作（删除文件、移动系统文件、执行任意命令）必须先请求用户确认
3. 操作完成后简要报告结果，不要啰嗦
4. 如果操作失败，说明原因并建议替代方案
5. 如果用户的请求不需要工具，直接回复即可
6. 用户要求「发给我/传到手机/下载」文件时，必须使用 send_file_to_user，禁止把文件二进制或全文读进聊天
7. 消息中含 `[用户上传文件]` 时：所列路径是**已落盘**位置；**禁止** curl/wget 从 Gateway 再下载。若用户要求移到某文件夹，**必须**用 move_file，源路径只能用 upload 块中的绝对路径，目标为用户指定目录

## 当前环境
- 设备: {device_id}
- 平台: {platform}
"""

TOOL_CALLING_INSTRUCTION = """
## 工具调用格式
当需要使用工具时，你必须输出以下格式的工具调用：
- 工具名称从「可用工具」列表中选择
- 参数必须符合工具的 JSON Schema 定义
- 一次可以调用多个工具

## 可用工具
{tools_description}
"""

MEMORY_CONTEXT_SECTION = """
## 长期记忆（Retrieved Context）
以下是从记忆库检索到的与当前任务相关的用户偏好或历史对话。请参考这些信息制定计划，避免重复询问用户已告知的偏好。
{retrieved_memory_context}
"""


class PromptManager:
    """System Prompt 管理器"""

    def __init__(
        self,
        device_id: str = "lingji-pc",
        platform: str = "Linux",
        registry: ToolRegistry | None = None,
    ):
        self.device_id = device_id
        self.platform = platform
        self.registry = registry

    def build_system_prompt(self, retrieved_memory_context: str = "") -> str:
        """构建完整 System Prompt"""
        prompt = BASE_SYSTEM_PROMPT.format(
            device_id=self.device_id,
            platform=self.platform,
        )

        if self.registry:
            tools_desc = self._format_tools()
            prompt += TOOL_CALLING_INSTRUCTION.format(
                tools_description=tools_desc,
            )

        if retrieved_memory_context.strip():
            prompt += MEMORY_CONTEXT_SECTION.format(
                retrieved_memory_context=retrieved_memory_context.strip(),
            )

        return prompt

    def _format_tools(self) -> str:
        """格式化工具列表为可读文本"""
        if not self.registry:
            return "（无可用工具）"

        lines = []
        for tool in self.registry.list_all():
            risk_icon = {"safe": "🟢", "warn": "🟡", "critical": "🔴"}.get(
                tool.risk.value, "⚪"
            )
            lines.append(f"- {risk_icon} **{tool.name}**: {tool.description}")
        return "\n".join(lines)

    def build_messages(
        self,
        user_text: str,
        history: list[dict] | None = None,
    ) -> list[dict]:
        """构建完整消息列表（system + history + user）"""
        messages = [{"role": "system", "content": self.build_system_prompt()}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages
