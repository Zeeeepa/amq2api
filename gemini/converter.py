"""
Gemini 请求格式转换器
将 Claude API 格式转换为 Gemini API 格式
"""
import logging
import uuid
import random
from typing import Dict, Any, List
from models import ClaudeRequest

logger = logging.getLogger(__name__)


def convert_claude_to_gemini(claude_req: ClaudeRequest, project: str) -> Dict[str, Any]:
    """
    将 Claude API 请求转换为 Gemini API 请求格式

    Args:
        claude_req: Claude 请求对象
        project: Gemini 项目 ID

    Returns:
        Gemini 请求字典
    """
    # 转换消息格式
    contents = []
    for msg in claude_req.messages:
        role = "user" if msg.role == "user" else "model"

        # 处理 content
        if isinstance(msg.content, str):
            parts = [{"text": msg.content}]
        elif isinstance(msg.content, list):
            parts = []
            for item in msg.content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})
                    elif item.get("type") == "image":
                        # 处理图片
                        source = item.get("source", {})
                        if source.get("type") == "base64":
                            parts.append({
                                "inlineData": {
                                    "mimeType": source.get("media_type", "image/png"),
                                    "data": source.get("data", "")
                                }
                            })
                    elif item.get("type") == "tool_use":
                        # 处理工具调用
                        parts.append({
                            "functionCall": {
                                "id": item.get("id"),
                                "name": item.get("name"),
                                "args": item.get("input", {})
                            }
                        })
                    elif item.get("type") == "tool_result":
                        # 处理工具结果
                        content = item.get("content", "")
                        if isinstance(content, list):
                            content = content[0].get("text", "") if content else ""
                        parts.append({
                            "functionResponse": {
                                "id": item.get("tool_use_id"),
                                "name": item.get("name", ""),
                                "response": {"output": content}
                            }
                        })
                else:
                    parts.append({"text": str(item)})
        else:
            parts = [{"text": str(msg.content)}]

        contents.append({
            "role": role,
            "parts": parts
        })

    # 构建 Gemini 请求
    gemini_request = {
        "project": project,
        "requestId": f"agent-{uuid.uuid4()}",
        "request": {
            "contents": contents,
            "generationConfig": {
                "temperature": claude_req.temperature if claude_req.temperature is not None else 0.4,
                "topP": 1,
                "topK": 40,
                "candidateCount": 1,
                "maxOutputTokens": claude_req.max_tokens,
                "stopSequences": ["<|user|>", "<|bot|>", "<|context_request|>", "<|endoftext|>", "<|end_of_turn|>"]
            },
            "sessionId": "-3750763034362895578",
        },
        "model": map_claude_model_to_gemini(claude_req.model),
        "userAgent": "antigravity/1.11.3 darwin/arm64",
        "requestType": "agent"
    }

    # 添加 system instruction
    if claude_req.system:
        gemini_request["request"]["systemInstruction"] = {
            "role": "user",
            "parts": [{"text": claude_req.system}]
        }

    # 添加工具
    if claude_req.tools:
        gemini_request["request"]["tools"] = convert_tools(claude_req.tools)
        gemini_request["request"]["toolConfig"] = {
            "functionCallingConfig": {
                "mode": "VALIDATED"
            }
        }

    return gemini_request


def map_claude_model_to_gemini(claude_model: str) -> str:
    """
    将 Claude 模型名称映射到 Gemini 模型名称
    如果请求的模型已经存在于支持列表中，则直接透传

    Args:
        claude_model: Claude 模型名称或 Gemini 模型名称

    Returns:
        Gemini 模型名称
    """
    # 支持的所有模型（直接透传）
    supported_models = {
        "gemini-2.5-flash", "gemini-2.5-flash-thinking", "gemini-2.5-pro",
        "gemini-3-pro-low", "gemini-3-pro-high", "gemini-2.5-flash-lite",
        "gemini-2.5-flash-image", "gemini-3-pro-image",
        "claude-sonnet-4-5", "claude-sonnet-4-5-thinking",
        "gpt-oss-120b-medium"
    }

    if claude_model in supported_models:
        return claude_model

    # Claude 标准模型名称映射
    model_mapping = {
        "claude-sonnet-4.5": "claude-sonnet-4-5",
        "claude-3-5-sonnet-20241022": "claude-sonnet-4-5",
        "claude-3-5-sonnet-20240620": "claude-sonnet-4-5",
        "claude-opus-4": "gemini-3-pro-high",
        "claude-haiku-4": "gemini-2.5-flash",
        "claude-3-haiku-20240307": "gemini-2.5-flash"
    }

    return model_mapping.get(claude_model, "claude-sonnet-4-5")


def convert_tools(claude_tools: List[Any]) -> List[Dict[str, Any]]:
    """
    将 Claude 工具格式转换为 Gemini 工具格式

    Args:
        claude_tools: Claude 工具列表

    Returns:
        Gemini 工具列表
    """
    gemini_tools = []

    for tool in claude_tools:
        gemini_tool = {
            "functionDeclarations": [{
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema
            }]
        }
        gemini_tools.append(gemini_tool)

    return gemini_tools