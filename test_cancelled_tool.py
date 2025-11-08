#!/usr/bin/env python3
"""
测试工具调用被取消的场景
"""
import json
from models import ClaudeRequest, ClaudeMessage
from converter import convert_claude_to_codewhisperer_request, codewhisperer_request_to_dict


def test_cancelled_tool_use():
    """测试工具调用被取消的场景"""
    print("=" * 60)
    print("测试场景：工具调用被取消")
    print("=" * 60)

    # 场景 1: 空文本的 tool_result
    print("\n场景 1: 空文本的 tool_result")
    messages = [
        ClaudeMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-123",
                    "content": [
                        {
                            "text": ""
                        }
                    ],
                    "status": "error"
                }
            ]
        )
    ]
    claude_req = ClaudeRequest(
        model="claude-sonnet-4.5",
        messages=messages,
        tools=None,
        stream=True
    )

    codewhisperer_req = convert_claude_to_codewhisperer_request(claude_req)
    result = codewhisperer_request_to_dict(codewhisperer_req)

    tool_results = result['conversationState']['currentMessage']['userInputMessage']['userInputMessageContext'].get('toolResults')
    print(f"Tool results: {json.dumps(tool_results, indent=2)}")
    print(f"Content text: {tool_results[0]['content'][0]['text']}")

    # 场景 2: 多个空文本的 tool_result
    print("\n场景 2: 多个空文本的 tool_result")
    messages = [
        ClaudeMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-456",
                    "content": [
                        {
                            "text": ""
                        },
                        {
                            "text": ""
                        }
                    ],
                    "status": "error"
                }
            ]
        )
    ]
    claude_req = ClaudeRequest(
        model="claude-sonnet-4.5",
        messages=messages,
        tools=None,
        stream=True
    )

    codewhisperer_req = convert_claude_to_codewhisperer_request(claude_req)
    result = codewhisperer_request_to_dict(codewhisperer_req)

    tool_results = result['conversationState']['currentMessage']['userInputMessage']['userInputMessageContext'].get('toolResults')
    print(f"Tool results: {json.dumps(tool_results, indent=2)}")
    print(f"Content text: {tool_results[0]['content'][0]['text']}")

    # 场景 3: 带实际内容的 tool_result
    print("\n场景 3: 带实际内容的 tool_result（不应添加默认文本）")
    messages = [
        ClaudeMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-789",
                    "content": [
                        {
                            "text": "File created successfully"
                        }
                    ],
                    "status": "success"
                }
            ]
        )
    ]
    claude_req = ClaudeRequest(
        model="claude-sonnet-4.5",
        messages=messages,
        tools=None,
        stream=True
    )

    codewhisperer_req = convert_claude_to_codewhisperer_request(claude_req)
    result = codewhisperer_request_to_dict(codewhisperer_req)

    tool_results = result['conversationState']['currentMessage']['userInputMessage']['userInputMessageContext'].get('toolResults')
    print(f"Tool results: {json.dumps(tool_results, indent=2)}")
    print(f"Content text: {tool_results[0]['content'][0]['text']}")
    print(f"Text unchanged: {tool_results[0]['content'][0]['text'] == 'File created successfully'}")

    # 场景 4: 混合（空文本 + 实际内容）
    print("\n场景 4: 混合（空文本 + 实际内容）")
    messages = [
        ClaudeMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-abc",
                    "content": [
                        {
                            "text": ""
                        },
                        {
                            "text": "Some result"
                        }
                    ],
                    "status": "success"
                }
            ]
        )
    ]
    claude_req = ClaudeRequest(
        model="claude-sonnet-4.5",
        messages=messages,
        tools=None,
        stream=True
    )

    codewhisperer_req = convert_claude_to_codewhisperer_request(claude_req)
    result = codewhisperer_request_to_dict(codewhisperer_req)

    tool_results = result['conversationState']['currentMessage']['userInputMessage']['userInputMessageContext'].get('toolResults')
    print(f"Tool results: {json.dumps(tool_results, indent=2)}")
    print(f"Content unchanged: {tool_results[0]['content'] == [{'text': ''}, {'text': 'Some result'}]}")

    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_cancelled_tool_use()
