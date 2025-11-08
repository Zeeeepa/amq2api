"""
测试消息合并功能
"""
from message_processor import process_claude_history_for_amazonq


def test_merge_consecutive_user_messages():
    """测试合并连续的用户消息（模拟实际 Claude Code 调用）"""
    print("测试场景 1: 合并连续的用户消息")

    # 模拟实际的历史记录（包含工具调用和结果）
    history = [
        {
            "userInputMessage": {
                "content": "<system-reminder>\nCalled the Read tool with the following input: {\"file_path\":\"/Users/songbingrong/tmp/target/111.txt\"}\n</system-reminder>",
                "userInputMessageContext": {"envState": {"operatingSystem": "macos"}},
                "origin": "CLI"
            }
        },
        {
            "userInputMessage": {
                "content": "<system-reminder>\nResult of calling the Read tool: \"     1→hello kitty\\n     2→\\n\\n\"</system-reminder>\n<system-reminder>\n[CLAUDE.md 内容]</system-reminder>\n\n@111.txt 帮我修改文件内容为hello kitty",
                "userInputMessageContext": {"envState": {"operatingSystem": "macos"}},
                "origin": "CLI"
            }
        },
        {
            "assistantResponseMessage": {
                "messageId": "78aca3ca-a367-49e0-9cc7-46dd979561b4",
                "content": "我已经读取了文件 `/Users/songbingrong/tmp/target/111.txt`，当前内容是：\n\n```\nhello kitty\n```\n\n文件内容已经是 \"hello kitty\" 了，与您要求的内容完全一致。无需进行任何修改。"
            }
        }
    ]

    print(f"  原始历史记录: {len(history)} 条消息")

    # 处理历史记录
    processed = process_claude_history_for_amazonq(history)

    print(f"  处理后: {len(processed)} 条消息")
    print(f"  消息类型: {[list(msg.keys())[0] for msg in processed]}")

    # 验证结果
    assert len(processed) == 2, f"期望 2 条消息，实际 {len(processed)} 条"
    assert "userInputMessage" in processed[0], "第一条应该是 userInputMessage"
    assert "assistantResponseMessage" in processed[1], "第二条应该是 assistantResponseMessage"

    # 验证内容合并
    merged_content = processed[0]["userInputMessage"]["content"]
    assert "Called the Read tool" in merged_content, "应包含工具调用内容"
    assert "Result of calling the Read tool" in merged_content, "应包含工具结果"
    assert "@111.txt 帮我修改文件内容为hello kitty" in merged_content, "应包含用户输入"

    print("  ✅ 通过：消息合并成功，user-assistant 交替正确")


def test_already_alternating():
    """测试已经交替的消息"""
    print("\n测试场景 2: 已交替的消息（不需要合并）")

    history = [
        {
            "userInputMessage": {
                "content": "用户消息1",
                "userInputMessageContext": {},
                "origin": "CLI"
            }
        },
        {
            "assistantResponseMessage": {
                "messageId": "123",
                "content": "助手响应1"
            }
        },
        {
            "userInputMessage": {
                "content": "用户消息2",
                "userInputMessageContext": {},
                "origin": "CLI"
            }
        },
        {
            "assistantResponseMessage": {
                "messageId": "456",
                "content": "助手响应2"
            }
        }
    ]

    print(f"  原始历史记录: {len(history)} 条消息")

    processed = process_claude_history_for_amazonq(history)

    print(f"  处理后: {len(processed)} 条消息")

    # 应该保持不变
    assert len(processed) == 4, f"期望 4 条消息，实际 {len(processed)} 条"

    print("  ✅ 通过：已交替消息保持不变")


def test_multiple_consecutive_users():
    """测试多个连续的用户消息"""
    print("\n测试场景 3: 多个连续的用户消息")

    history = [
        {"userInputMessage": {"content": "消息1", "origin": "CLI"}},
        {"userInputMessage": {"content": "消息2", "origin": "CLI"}},
        {"userInputMessage": {"content": "消息3", "origin": "CLI"}},
        {"assistantResponseMessage": {"content": "助手响应", "messageId": "123"}},
    ]

    print(f"  原始历史记录: {len(history)} 条消息")

    processed = process_claude_history_for_amazonq(history)

    print(f"  处理后: {len(processed)} 条消息")

    # 验证合并
    assert len(processed) == 2, f"期望 2 条消息，实际 {len(processed)} 条"
    assert "userInputMessage" in processed[0]
    assert "assistantResponseMessage" in processed[1]

    # 验证内容
    merged = processed[0]["userInputMessage"]["content"]
    assert "消息1" in merged and "消息2" in merged and "消息3" in merged

    print("  ✅ 通过：多个连续消息合并成功")


def test_empty_history():
    """测试空历史记录"""
    print("\n测试场景 4: 空历史记录")

    history = []
    processed = process_claude_history_for_amazonq(history)
    assert len(processed) == 0, "空历史记录应返回空列表"
    print("  ✅ 通过：空历史记录处理正确")


def test_trailing_user_messages():
    """测试末尾的用户消息（没有后续的 assistant）"""
    print("\n测试场景 5: 末尾的用户消息")

    history = [
        {"assistantResponseMessage": {"content": "助手响应", "messageId": "123"}},
        {"userInputMessage": {"content": "新的用户消息", "origin": "CLI"}},
    ]

    print(f"  原始历史记录: {len(history)} 条消息")

    processed = process_claude_history_for_amazonq(history)

    print(f"  处理后: {len(processed)} 条消息")

    # 验证处理
    assert len(processed) == 2, f"期望 2 条消息，实际 {len(processed)} 条"

    print("  ✅ 通过：末尾用户消息处理正确")


if __name__ == "__main__":
    print("=" * 60)
    print("开始测试消息合并功能")
    print("=" * 60)

    test_merge_consecutive_user_messages()
    test_already_alternating()
    test_multiple_consecutive_users()
    test_empty_history()
    test_trailing_user_messages()

    print("\n" + "=" * 60)
    print("🎉 所有测试通过！")
    print("=" * 60)
