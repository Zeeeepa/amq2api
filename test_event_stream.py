"""
Event Stream 解析器测试脚本
"""
import asyncio
import struct
import json


async def test_event_stream_parser():
    """测试 Event Stream 解析器"""
    print("=" * 60)
    print("测试 AWS Event Stream 解析器")
    print("=" * 60)

    from event_stream_parser import EventStreamParser, extract_event_info
    from parser import parse_amazonq_event

    # 构建测试消息
    def build_test_message(event_type: str, payload: dict) -> bytes:
        """构建测试用的 Event Stream 消息"""
        # 构建 payload
        payload_bytes = json.dumps(payload).encode('utf-8')

        # 构建 headers
        headers = []

        # :event-type header
        name = b':event-type'
        value = event_type.encode('utf-8')
        header = (
            bytes([len(name)]) +
            name +
            bytes([7]) +  # String type
            struct.pack('>H', len(value)) +
            value
        )
        headers.append(header)

        # :content-type header
        name = b':content-type'
        value = b'application/json'
        header = (
            bytes([len(name)]) +
            name +
            bytes([7]) +
            struct.pack('>H', len(value)) +
            value
        )
        headers.append(header)

        # :message-type header
        name = b':message-type'
        value = b'event'
        header = (
            bytes([len(name)]) +
            name +
            bytes([7]) +
            struct.pack('>H', len(value)) +
            value
        )
        headers.append(header)

        headers_bytes = b''.join(headers)

        # 计算总长度
        total_length = 12 + len(headers_bytes) + len(payload_bytes) + 4

        # 构建 prelude
        prelude = (
            struct.pack('>I', total_length) +
            struct.pack('>I', len(headers_bytes)) +
            struct.pack('>I', 0)  # CRC (简化为 0)
        )

        # 构建完整消息
        message = prelude + headers_bytes + payload_bytes + struct.pack('>I', 0)

        return message

    # 测试 1: initial-response 事件
    print("\n测试 1: initial-response 事件")
    print("-" * 60)

    message1 = build_test_message('initial-response', {'conversationId': 'test-123'})
    parsed1 = EventStreamParser.parse_message(message1)

    if parsed1:
        print(f"✓ 消息解析成功")
        event_info1 = extract_event_info(parsed1)
        print(f"  Event Type: {event_info1['event_type']}")
        print(f"  Payload: {event_info1['payload']}")

        event1 = parse_amazonq_event(event_info1)
        if event1:
            print(f"✓ 事件转换成功: {type(event1).__name__}")
        else:
            print(f"✗ 事件转换失败")
    else:
        print(f"✗ 消息解析失败")

    # 测试 2: assistantResponseEvent 事件
    print("\n测试 2: assistantResponseEvent 事件")
    print("-" * 60)

    message2 = build_test_message('assistantResponseEvent', {'content': 'Hello, world!'})
    parsed2 = EventStreamParser.parse_message(message2)

    if parsed2:
        print(f"✓ 消息解析成功")
        event_info2 = extract_event_info(parsed2)
        print(f"  Event Type: {event_info2['event_type']}")
        print(f"  Payload: {event_info2['payload']}")

        event2 = parse_amazonq_event(event_info2)
        if event2:
            print(f"✓ 事件转换成功: {type(event2).__name__}")
            if hasattr(event2, 'delta') and event2.delta:
                print(f"  Content: {event2.delta.text}")
        else:
            print(f"✗ 事件转换失败")
    else:
        print(f"✗ 消息解析失败")

    # 测试 3: 流式解析
    print("\n测试 3: 流式解析")
    print("-" * 60)

    async def mock_byte_stream():
        """模拟字节流"""
        messages = [
            build_test_message('initial-response', {'conversationId': 'stream-test'}),
            build_test_message('assistantResponseEvent', {'content': 'Hi'}),
            build_test_message('assistantResponseEvent', {'content': '! I\'m'}),
            build_test_message('assistantResponseEvent', {'content': ' Amazon Q'}),
        ]

        for msg in messages:
            yield msg

    count = 0
    async for message in EventStreamParser.parse_stream(mock_byte_stream()):
        event_info = extract_event_info(message)
        event = parse_amazonq_event(event_info)
        if event:
            count += 1
            print(f"  事件 {count}: {type(event).__name__}")

    print(f"✓ 成功解析 {count} 个事件")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_event_stream_parser())