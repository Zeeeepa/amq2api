"""
SSE 流处理模块（更新版）
处理 Amazon Q Event Stream 响应并转换为 Claude 格式
"""
import logging
from typing import AsyncIterator, Optional
from event_stream_parser import EventStreamParser, extract_event_info
from parser import (
    parse_amazonq_event,
    build_claude_message_start_event,
    build_claude_content_block_start_event,
    build_claude_content_block_delta_event,
    build_claude_content_block_stop_event,
    build_claude_message_stop_event,
    build_claude_tool_use_start_event,
    build_claude_tool_use_input_delta_event
)
from models import (
    MessageStart,
    ContentBlockDelta,
    ContentBlockStop,
    MessageStop,
    AssistantResponseEnd
)

logger = logging.getLogger(__name__)


class AmazonQStreamHandler:
    """Amazon Q Event Stream 处理器"""

    def __init__(self, model: str = "claude-sonnet-4.5"):
        # 响应文本累积缓冲区
        self.response_buffer: list[str] = []

        # 内容块索引
        self.content_block_index: int = -1

        # 内容块是否已开始
        self.content_block_started: bool = False

        # 内容块开始是否已发送
        self.content_block_start_sent: bool = False

        # 内容块停止是否已发送
        self.content_block_stop_sent: bool = False

        # 对话 ID
        self.conversation_id: Optional[str] = None

        # 输入 token 数量
        self.input_tokens: int = 0

        # 是否已发送 message_start
        self.message_start_sent: bool = False

        # 原始请求的 model
        self.model: str = model

        # Tool use 相关状态
        self.current_tool_use: Optional[dict] = None  # 当前正在处理的工具调用
        self.tool_input_buffer: list[str] = []  # 累积 tool input 片段
        self.tool_use_id: Optional[str] = None  # 当前 tool use ID
        self.tool_name: Optional[str] = None  # 当前 tool name

        # 已处理的 tool_use_id 集合（用于去重）
        self._processed_tool_use_ids: set = set()

    async def handle_stream(
        self,
        upstream_bytes: AsyncIterator[bytes]
    ) -> AsyncIterator[str]:
        """
        处理上游 Event Stream 并转换为 Claude 格式

        Args:
            upstream_bytes: 上游字节流（Amazon Q Event Stream）

        Yields:
            str: Claude 格式的 SSE 事件
        """
        try:
            # 使用 Event Stream 解析器
            parser = EventStreamParser()

            async for message in parser.parse_stream(upstream_bytes):
                # 提取事件信息
                event_info = extract_event_info(message)
                if not event_info:
                    continue

                # 记录收到的事件类型
                event_type = event_info.get('event_type')
                logger.info(f"收到 Amazon Q 事件: {event_type}")

                # 记录完整的事件信息（调试级别）
                import json
                logger.debug(f"事件详情: {json.dumps(event_info, ensure_ascii=False, indent=2)}")

                # 解析为标准事件对象
                event = parse_amazonq_event(event_info)
                if not event:
                    # 检查是否是 toolUseEvent 的原始 payload
                    if event_type == 'toolUseEvent':
                        logger.info(f"处理 toolUseEvent: {event_info.get('payload', {})}")
                        # 直接处理 tool use 事件
                        async for cli_event in self._handle_tool_use_event(event_info.get('payload', {})):
                            yield cli_event
                    else:
                        logger.warning(f"跳过未知事件类型: {event_type}")
                    continue

                # 根据事件类型处理
                if isinstance(event, MessageStart):
                    # 处理 initial-response 事件
                    if event.message:
                        self.conversation_id = event.message.conversationId

                    # 发送 message_start
                    if not self.message_start_sent:
                        cli_event = build_claude_message_start_event(
                            self.conversation_id or "unknown",
                            self.model
                        )
                        yield cli_event
                        self.message_start_sent = True

                elif isinstance(event, ContentBlockDelta):
                    # 处理 assistantResponseEvent 事件

                    # 首次收到内容时，发送 content_block_start
                    if not self.content_block_start_sent:
                        # 内容块索引递增
                        self.content_block_index += 1
                        cli_event = build_claude_content_block_start_event(
                            self.content_block_index
                        )
                        yield cli_event
                        self.content_block_start_sent = True
                        self.content_block_started = True

                    # 发送内容增量
                    if event.delta and event.delta.text:
                        text_chunk = event.delta.text

                        # 追加到缓冲区
                        self.response_buffer.append(text_chunk)

                        # 构建并发送事件
                        cli_event = build_claude_content_block_delta_event(
                            self.content_block_index,
                            text_chunk
                        )
                        yield cli_event

                elif isinstance(event, AssistantResponseEnd):
                    # 处理助手响应结束事件
                    logger.info(f"收到助手响应结束事件，toolUses数量: {len(event.tool_uses)}")

                    # Note: toolUses 已经在 toolUseEvent 中处理，这里不需要重复处理
                    # 检查是否需要发送 content_block_stop
                    if self.content_block_started and not self.content_block_stop_sent:
                        cli_event = build_claude_content_block_stop_event(
                            self.content_block_index
                        )
                        yield cli_event
                        self.content_block_stop_sent = True

            # 流结束，发送收尾事件
            # 只有当 content_block_started 且尚未发送 content_block_stop 时才发送
            if self.content_block_started and not self.content_block_stop_sent:
                cli_event = build_claude_content_block_stop_event(
                    self.content_block_index
                )
                yield cli_event
                self.content_block_stop_sent = True

            # 计算 token 数量并发送 message_stop
            full_response = "".join(self.response_buffer)
            output_tokens = self._count_tokens(full_response)

            cli_event = build_claude_message_stop_event(
                self.input_tokens,
                output_tokens,
                "end_turn"
            )
            yield cli_event

        except Exception as e:
            logger.error(f"处理流时发生错误: {e}", exc_info=True)
            raise

    async def _handle_tool_use_event(self, payload: dict) -> AsyncIterator[str]:
        """
        处理 tool use 事件

        Args:
            payload: tool use 事件的 payload

        Yields:
            str: Claude 格式的 tool use 事件
        """
        try:
            # 提取 tool use 信息
            tool_use_id = payload.get('toolUseId')
            tool_name = payload.get('name')
            tool_input = payload.get('input', {})
            is_stop = payload.get('stop', False)

            logger.info(f"Tool use 事件 - ID: {tool_use_id}, Name: {tool_name}, Stop: {is_stop}")
            logger.debug(f"Tool input: {tool_input}")

            # 添加去重机制：检查是否已经处理过这个 tool_use_id
            # if tool_use_id and not is_stop:
                # 如果这个 tool_use_id 已经在当前工具调用中，说明是重复事件
                # if self.tool_use_id == tool_use_id and self.current_tool_use:
                #     logger.warning(f"检测到重复的 tool use 事件，toolUseId={tool_use_id}，跳过处理")
                #     return
                # # 如果这个 tool_use_id 之前处理过但已经完成，也是重复事件
                # elif tool_use_id in self._processed_tool_use_ids:
                #     logger.warning(f"检测到已处理过的 tool use 事件，toolUseId={tool_use_id}，跳过处理")
                #     return

            # 如果是新 tool use 事件的开始
            if tool_use_id and tool_name and not self.current_tool_use:
                logger.info(f"开始新的 tool use: {tool_name} (ID: {tool_use_id})")

                # 记录这个 tool_use_id 为已处理
                self._processed_tool_use_ids.add(tool_use_id)

                # 内容块索引递增
                self.content_block_index += 1

                # 发送 content_block_start (tool_use type)
                cli_event = build_claude_tool_use_start_event(
                    self.content_block_index,
                    tool_use_id,
                    tool_name
                )
                logger.debug(f"发送 content_block_start (tool_use): index={self.content_block_index}")
                yield cli_event

                self.content_block_started = True
                self.current_tool_use = {
                    'toolUseId': tool_use_id,
                    'name': tool_name
                }
                self.tool_use_id = tool_use_id
                self.tool_name = tool_name
                self.tool_input_buffer = []  # 用于累积字符串片段

            # 如果是正在处理的 tool use，累积 input 片段
            if self.current_tool_use and tool_input:
                # Amazon Q 的 input 是字符串片段，需要累积
                # 注意：tool_input 可能是字符串或字典
                if isinstance(tool_input, str):
                    # 字符串片段，直接累积
                    input_fragment = tool_input
                    self.tool_input_buffer.append(input_fragment)
                    logger.debug(f"累积 input 片段: '{input_fragment}' (总长度: {sum(len(s) for s in self.tool_input_buffer)})")
                elif isinstance(tool_input, dict):
                    # 如果是字典，转换为 JSON 字符串
                    import json
                    input_fragment = json.dumps(tool_input, ensure_ascii=False)
                    self.tool_input_buffer.append(input_fragment)
                    logger.debug(f"累积 input 对象: {len(input_fragment)} 字符")
                else:
                    logger.warning(f"未知的 input 类型: {type(tool_input)}")
                    input_fragment = str(tool_input)
                    self.tool_input_buffer.append(input_fragment)

                # 发送 input_json_delta（发送原始片段）
                cli_event = build_claude_tool_use_input_delta_event(
                    self.content_block_index,
                    input_fragment
                )
                yield cli_event

            # 如果是 stop 事件，发送 content_block_stop
            if is_stop and self.current_tool_use:
                # 记录完整的累积 input
                full_input = "".join(self.tool_input_buffer)
                logger.info(f"完成 tool use: {self.tool_name} (ID: {self.tool_use_id})")
                logger.info(f"完整 input ({len(full_input)} 字符): {full_input}")

                cli_event = build_claude_content_block_stop_event(
                    self.content_block_index
                )
                logger.debug(f"发送 content_block_stop: index={self.content_block_index}")
                yield cli_event

                # 标记 content_block_stop 已发送，避免重复发送
                self.content_block_stop_sent = True
                # 重置 content_started 状态
                self.content_block_started = False

                # 清理状态
                self.current_tool_use = None
                self.tool_use_id = None
                self.tool_name = None
                self.tool_input_buffer = []

        except Exception as e:
            logger.error(f"处理 tool use 事件失败: {e}", exc_info=True)
            raise

    def _count_tokens(self, text: str) -> int:
        """
        计算文本的 token 数量
        简化实现：平均每 4 个字符约等于 1 个 token

        Args:
            text: 文本内容

        Returns:
            int: token 数量（估算）
        """
        return max(1, len(text) // 4)


async def handle_amazonq_stream(
    upstream_bytes: AsyncIterator[bytes],
    model: str = "claude-sonnet-4.5"
) -> AsyncIterator[str]:
    """
    处理 Amazon Q Event Stream 的便捷函数

    Args:
        upstream_bytes: 上游字节流
        model: 原始请求的 model 名称

    Yields:
        str: Claude 格式的 SSE 事件
    """
    handler = AmazonQStreamHandler(model=model)
    async for event in handler.handle_stream(upstream_bytes):
        yield event