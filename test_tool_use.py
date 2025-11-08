#!/usr/bin/env python3
"""
测试 tool use 事件处理逻辑
"""
import asyncio
import json
from stream_handler_new import AmazonQStreamHandler
from parser import build_claude_tool_use_start_event, build_claude_tool_use_input_delta_event


async def test_tool_use_event():
    """测试 tool use 事件处理"""
    print("=" * 60)
    print("测试 Tool Use 事件处理")
    print("=" * 60)

    # 创建 handler
    handler = AmazonQStreamHandler(model="claude-sonnet-4.5")

    # 模拟 tool use 事件的 payload
    tool_use_payload = {
        "toolUseId": "test-tool-123",
        "name": "get_weather",
        "input": {
            "location": "Beijing",
            "unit": "celsius"
        },
        "stop": True
    }

    # 处理 tool use 事件
    print("\n1. 发送 Tool Use 事件:")
    print(f"   Payload: {json.dumps(tool_use_payload, ensure_ascii=False, indent=2)}")

    async for cli_event in handler._handle_tool_use_event(tool_use_payload):
        print(f"\n2. 生成的 Claude 事件:")
        # 解析并美化输出
        for line in cli_event.strip().split('\n'):
            if line:
                print(f"   {line}")
        print()


async def test_content_block_index():
    """测试内容块索引递增"""
    print("=" * 60)
    print("测试内容块索引递增")
    print("=" * 60)

    handler = AmazonQStreamHandler(model="claude-sonnet-4.5")

    # 模拟多个内容块
    print(f"\n初始 index: {handler.content_block_index}")

    # 第一次递增（tool use）
    handler.content_block_index += 1
    print(f"第一个内容块后 index: {handler.content_block_index}")

    # 第二次递增（text）
    handler.content_block_index += 1
    print(f"第二个内容块后 index: {handler.content_block_index}")

    # 第三次递增（tool use）
    handler.content_block_index += 1
    print(f"第三个内容块后 index: {handler.content_block_index}")


async def test_build_events():
    """测试构建 Claude 事件"""
    print("=" * 60)
    print("测试构建 Claude 事件")
    print("=" * 60)

    # 测试 tool use start 事件
    print("\n1. Tool Use Start 事件:")
    event = build_claude_tool_use_start_event(0, "tool-123", "get_weather")
    for line in event.strip().split('\n'):
        if line:
            print(f"   {line}")

    # 测试 tool use input delta 事件
    print("\n2. Tool Use Input Delta 事件:")
    event = build_claude_tool_use_input_delta_event(
        0,
        '{"location": "Beijing", "unit": "celsius"}'
    )
    for line in event.strip().split('\n'):
        if line:
            print(f"   {line}")


async def main():
    """主测试函数"""
    await test_build_events()
    await test_content_block_index()
    await test_tool_use_event()

    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
