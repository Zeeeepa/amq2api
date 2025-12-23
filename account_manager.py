"""
账号管理模块
负责多账号的数据库操作和管理
"""
import sqlite3
import json
import uuid
import time
import random
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 数据库路径
# 优先使用 /app/data 目录（Docker 卷），否则使用当前目录
import os
if os.path.exists("/app/data"):
    DB_PATH = Path("/app/data/accounts.db")
else:
    DB_PATH = Path(__file__).parent / "accounts.db"


def _ensure_db():
    """初始化数据库表结构"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                label TEXT,
                clientId TEXT,
                clientSecret TEXT,
                refreshToken TEXT,
                accessToken TEXT,
                other TEXT,
                last_refresh_time TEXT,
                last_refresh_status TEXT,
                created_at TEXT,
                updated_at TEXT,
                enabled INTEGER DEFAULT 1,
                type TEXT DEFAULT 'amazonq',
                rate_limit_per_hour INTEGER DEFAULT 20
            )
            """
        )

        # 迁移：为已存在的表添加字段
        cursor = conn.execute("PRAGMA table_info(accounts)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'type' not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN type TEXT DEFAULT 'amazonq'")
        if 'rate_limit_per_hour' not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN rate_limit_per_hour INTEGER DEFAULT 20")

        # 创建调用记录表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                model TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
            """
        )

        # 创建索引以加速查询
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_call_logs_account_timestamp
            ON call_logs(account_id, timestamp)
            """
        )

        # 创建配置表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
            """
        )

        # 初始化默认配置
        _init_default_config(conn)

        conn.commit()


def _init_default_config(conn):
    """初始化默认配置"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    # 默认配置
    defaults = {
        "gemini_only_models": json.dumps([
            "claude-sonnet-4-5-thinking",
            "claude-opus-4-5-thinking",
            "gemini-3-flash"
        ]),
        "amazonq_only_models": json.dumps([
            "claude-sonnet-4",
            "claude-sonnet-4.5",
            "claude-haiku-4.5"
        ]),
        "supported_models": json.dumps([
            "gemini-2.5-flash", "gemini-2.5-flash-thinking", "gemini-2.5-pro",
            "gemini-3-pro-low", "gemini-3-pro-high", "gemini-2.5-flash-lite",
            "gemini-2.5-flash-image", "claude-sonnet-4-5", "claude-sonnet-4-5-thinking",
            "claude-opus-4-5-thinking", "gpt-oss-120b-medium", "gemini-3-flash"
        ]),
        "model_mapping": json.dumps({
            "claude-sonnet-4.5": "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022": "claude-sonnet-4-5",
            "claude-3-5-sonnet-20240620": "claude-sonnet-4-5",
            "claude-opus-4": "gemini-3-pro-high",
            "claude-haiku-4": "claude-haiku-4.5",
            "claude-3-haiku-20240307": "gemini-2.5-flash"
        })
    }

    for key, value in defaults.items():
        existing = conn.execute("SELECT 1 FROM config WHERE key=?", (key,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)", (key, value, now))


def _conn() -> sqlite3.Connection:
    """创建数据库连接"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    """将数据库行转换为字典"""
    d = dict(r)
    if d.get("other"):
        try:
            d["other"] = json.loads(d["other"])
        except Exception:
            pass
    if "enabled" in d and d["enabled"] is not None:
        d["enabled"] = bool(int(d["enabled"]))
    return d


def list_enabled_accounts(account_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取所有启用的账号"""
    with _conn() as conn:
        if account_type:
            rows = conn.execute("SELECT * FROM accounts WHERE enabled=1 AND type=? ORDER BY created_at DESC", (account_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM accounts WHERE enabled=1 ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_random_account(account_type: Optional[str] = None, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """随机选择一个启用的账号（自动过滤限流和配额不足的账号）

    Args:
        account_type: 账号类型 ('amazonq' 或 'gemini')
        model: 请求的模型名称（用于 Gemini 账号配额检查）

    Returns:
        符合条件的随机账号，如果没有可用账号则返回 None
    """
    accounts = list_enabled_accounts(account_type)
    if not accounts:
        return None

    # 过滤掉已达到限流的账号
    available_accounts = []
    for account in accounts:
        # 检查限流
        if not check_rate_limit(account['id']):
            logger.debug(f"账号 {account.get('label')} (ID: {account.get('id')[:8]}...) 已达到限流，跳过")
            continue

        # 如果是 Gemini 账号且指定了模型，需要检查配额
        if account_type == "gemini" and model:
            if not is_model_available_for_account(account, model):
                logger.debug(f"账号 {account.get('label')} (ID: {account.get('id')[:8]}...) 模型 {model} 配额不足，跳过")
                continue

        available_accounts.append(account)

    if not available_accounts:
        if account_type == "gemini" and model:
            logger.warning(f"没有可用的 Gemini 账号支持模型 {model}（所有账号都已限流或配额不足）")
        else:
            logger.warning(f"没有可用的 {account_type or '任何类型'} 账号（所有账号都已限流）")
        return None

    selected = random.choice(available_accounts)
    logger.info(f"随机选择了账号: {selected.get('label')} (ID: {selected.get('id')[:8]}...)")
    return selected


def get_config(key: str) -> Optional[Any]:
    """获取配置值"""
    with _conn() as conn:
        row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except:
            return row[0]


def set_config(key: str, value: Any) -> None:
    """设置配置值"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    value_str = json.dumps(value) if not isinstance(value, str) else value
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value_str, now)
        )
        conn.commit()


def get_all_config() -> Dict[str, Any]:
    """获取所有配置"""
    with _conn() as conn:
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        result = {}
        for row in rows:
            try:
                result[row[0]] = json.loads(row[1])
            except:
                result[row[0]] = row[1]
        return result


def get_random_channel_by_model(model: str) -> Optional[str]:
    """根据模型智能选择渠道（按账号数量加权）

    Args:
        model: 请求的模型名称

    Returns:
        渠道名称 ('amazonq' 或 'gemini')，如果没有可用账号则返回 None
    """
    # 从数据库读取配置
    gemini_only_models = get_config("gemini_only_models") or []
    amazonq_only_models = get_config("amazonq_only_models") or []

    # 如果是 Gemini 独占模型（以 gemini 开头或在独占列表中）
    if model.startswith('gemini') or model in gemini_only_models:
        gemini_accounts = list_enabled_accounts(account_type='gemini')
        if gemini_accounts:
            return 'gemini'
        return None

    # 如果是 Amazon Q 独占模型
    if model in amazonq_only_models:
        amazonq_accounts = list_enabled_accounts(account_type='amazonq')
        if amazonq_accounts:
            return 'amazonq'
        return None

    # 对于其他模型（两个渠道都支持），按账号数量加权随机选择
    amazonq_accounts = list_enabled_accounts(account_type='amazonq')
    gemini_accounts = list_enabled_accounts(account_type='gemini')

    amazonq_count = len(amazonq_accounts)
    gemini_count = len(gemini_accounts)

    # 如果没有任何可用账号
    if amazonq_count == 0 and gemini_count == 0:
        return None

    # 如果只有一个渠道有账号
    if amazonq_count == 0:
        return 'gemini'
    if gemini_count == 0:
        return 'amazonq'

    # 按账号数量加权随机选择
    total = amazonq_count + gemini_count
    rand = random.randint(1, total)

    if rand <= amazonq_count:
        return 'amazonq'
    else:
        return 'gemini'


def get_account(account_id: str) -> Optional[Dict[str, Any]]:
    """根据ID获取账号"""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            return None
        return _row_to_dict(row)


def create_account(
    label: Optional[str],
    client_id: str,
    client_secret: str,
    refresh_token: Optional[str] = None,
    access_token: Optional[str] = None,
    other: Optional[Dict[str, Any]] = None,
    enabled: bool = True,
    account_type: str = "amazonq"
) -> Dict[str, Any]:
    """创建新账号"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    acc_id = str(uuid.uuid4())
    other_str = json.dumps(other, ensure_ascii=False) if other else None

    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO accounts (id, label, clientId, clientSecret, refreshToken, accessToken, other, last_refresh_time, last_refresh_status, created_at, updated_at, enabled, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (acc_id, label, client_id, client_secret, refresh_token, access_token, other_str, None, "never", now, now, 1 if enabled else 0, account_type)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
        return _row_to_dict(row)


def update_account(
    account_id: str,
    label: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None,
    access_token: Optional[str] = None,
    other: Optional[Dict[str, Any]] = None,
    enabled: Optional[bool] = None
) -> Optional[Dict[str, Any]]:
    """更新账号信息"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    fields = []
    values: List[Any] = []

    if label is not None:
        fields.append("label=?")
        values.append(label)
    if client_id is not None:
        fields.append("clientId=?")
        values.append(client_id)
    if client_secret is not None:
        fields.append("clientSecret=?")
        values.append(client_secret)
    if refresh_token is not None:
        fields.append("refreshToken=?")
        values.append(refresh_token)
    if access_token is not None:
        fields.append("accessToken=?")
        values.append(access_token)
    if other is not None:
        fields.append("other=?")
        values.append(json.dumps(other, ensure_ascii=False))
    if enabled is not None:
        fields.append("enabled=?")
        values.append(1 if enabled else 0)

    if not fields:
        return get_account(account_id)

    fields.append("updated_at=?")
    values.append(now)
    values.append(account_id)

    with _conn() as conn:
        cur = conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return _row_to_dict(row)


def update_account_tokens(
    account_id: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    status: str = "success"
) -> Optional[Dict[str, Any]]:
    """更新账号的 token 信息"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

    with _conn() as conn:
        if refresh_token:
            conn.execute(
                """
                UPDATE accounts
                SET accessToken=?, refreshToken=?, last_refresh_time=?, last_refresh_status=?, updated_at=?
                WHERE id=?
                """,
                (access_token, refresh_token, now, status, now, account_id)
            )
        else:
            conn.execute(
                """
                UPDATE accounts
                SET accessToken=?, last_refresh_time=?, last_refresh_status=?, updated_at=?
                WHERE id=?
                """,
                (access_token, now, status, now, account_id)
            )
        conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return _row_to_dict(row) if row else None


def update_refresh_status(account_id: str, status: str) -> None:
    """更新账号的刷新状态"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET last_refresh_time=?, last_refresh_status=?, updated_at=? WHERE id=?",
            (now, status, now, account_id)
        )
        conn.commit()


def delete_account(account_id: str) -> bool:
    """删除账号"""
    with _conn() as conn:
        cur = conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        conn.commit()
        return cur.rowcount > 0


def list_all_accounts() -> List[Dict[str, Any]]:
    """获取所有账号"""
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]


def is_model_available_for_account(account: Dict[str, Any], model: str) -> bool:
    """检查账号的指定模型是否有配额可用

    Args:
        account: 账号信息
        model: 模型名称

    Returns:
        True 如果模型可用，False 如果配额已用完或需要等待重置
    """
    other = account.get("other", {})
    if isinstance(other, str):
        try:
            other = json.loads(other)
        except json.JSONDecodeError:
            return True  # 如果解析失败，默认认为可用

    if not other:
        other = {}
    credits_info = other.get("creditsInfo", {})
    models = credits_info.get("models", {})

    # 如果没有该模型的配额信息，默认认为可用
    if model not in models:
        return True

    model_info = models[model]
    remaining_fraction = model_info.get("remainingFraction", 1.0)
    reset_time_str = model_info.get("resetTime")

    # 如果配额大于 0，可用
    if remaining_fraction > 0:
        return True

    # 如果配额为 0，检查是否已经到重置时间，并尝试自动恢复
    if reset_time_str:
        try:
            reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)

            # 如果已经过了重置时间，尝试自动恢复配额
            if now >= reset_time:
                account_id = account.get('id')
                if account_id and restore_model_quota_if_needed(account_id, model):
                    logger.info(f"模型 {model} 配额已自动恢复，账号 {account_id} 可用")
                    return True
        except Exception as e:
            logger.error(f"解析重置时间失败: {e}")

    logger.debug(f"模型 {model} 配额不足，账号 {account.get('id')} 不可用")
    return False


def restore_model_quota_if_needed(account_id: str, model: str) -> bool:
    """检查并恢复模型配额（如果已到重置时间）

    Args:
        account_id: 账号 ID
        model: 模型名称

    Returns:
        True 如果配额已恢复，False 如果仍需等待
    """
    account = get_account(account_id)
    if not account:
        logger.error(f"账号 {account_id} 不存在")
        return False

    other = account.get("other", {})
    if isinstance(other, str):
        try:
            other = json.loads(other)
        except json.JSONDecodeError:
            return False

    credits_info = other.get("creditsInfo", {})
    models = credits_info.get("models", {})

    if model not in models:
        return True  # 没有配额信息，认为可用

    model_info = models[model]
    remaining_fraction = model_info.get("remainingFraction", 1.0)
    reset_time_str = model_info.get("resetTime")

    # 如果配额已经大于 0，不需要恢复
    if remaining_fraction > 0:
        return True

    # 检查是否已到重置时间
    if reset_time_str:
        try:
            reset_time = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)

            if now >= reset_time:
                # 已到重置时间，恢复配额为 1.0
                model_info["remainingFraction"] = 1.0
                model_info["remainingPercent"] = 100

                # 更新数据库
                update_account(account_id, other=other)
                logger.info(f"已自动恢复账号 {account_id} 的模型 {model} 配额")
                return True
        except Exception as e:
            logger.error(f"恢复配额时出错: {e}")

    return False


def mark_model_exhausted(account_id: str, model: str, reset_time: str) -> None:
    """标记账号的某个模型配额已用完

    Args:
        account_id: 账号 ID
        model: 模型名称
        reset_time: 配额重置时间 (ISO 8601 格式)
    """
    account = get_account(account_id)
    if not account:
        logger.error(f"账号 {account_id} 不存在")
        return

    other = account.get("other", {})
    if isinstance(other, str):
        try:
            other = json.loads(other)
        except json.JSONDecodeError:
            other = {}

    # 保 creditsInfo 结构存在
    if "creditsInfo" not in other:
        other["creditsInfo"] = {"models": {}, "summary": {"totalModels": 0, "averageRemaining": 0}}

    credits_info = other["creditsInfo"]
    if "models" not in credits_info:
        credits_info["models"] = {}

    # 更新模型配额信息
    if model not in credits_info["models"]:
        credits_info["models"][model] = {}

    credits_info["models"][model]["remainingFraction"] = 0
    credits_info["models"][model]["remainingPercent"] = 0
    credits_info["models"][model]["resetTime"] = reset_time

    # 更新数据库
    update_account(account_id, other=other)
    logger.info(f"已标记账号 {account_id} 的模型 {model} 配额用完，重置时间: {reset_time}")


def record_api_call(account_id: str, model: Optional[str] = None) -> None:
    """记录账号的 API 调用

    Args:
        account_id: 账号 ID
        model: 使用的模型名称
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    with _conn() as conn:
        conn.execute(
            "INSERT INTO call_logs (account_id, timestamp, model) VALUES (?, ?, ?)",
            (account_id, now, model)
        )
        conn.commit()


def check_rate_limit(account_id: str) -> bool:
    """检查账号是否超过速率限制（滑动窗口）

    Args:
        account_id: 账号 ID

    Returns:
        True 如果未超过限制，False 如果已超过限制
    """
    account = get_account(account_id)
    if not account:
        return False

    rate_limit = account.get("rate_limit_per_hour", 20)

    # 计算一小时前的时间戳
    one_hour_ago = datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=1)
    one_hour_ago_str = one_hour_ago.strftime("%Y-%m-%dT%H:%M:%S")

    # 查询过去一小时内的调用次数
    with _conn() as conn:
        result = conn.execute(
            "SELECT COUNT(*) FROM call_logs WHERE account_id=? AND timestamp >= ?",
            (account_id, one_hour_ago_str)
        ).fetchone()

        call_count = result[0] if result else 0

    return call_count < rate_limit


def get_account_call_stats(account_id: str) -> Dict[str, Any]:
    """获取账号的调用统计信息

    Args:
        account_id: 账号 ID

    Returns:
        包含调用统计的字典
    """
    account = get_account(account_id)
    if not account:
        return {}

    rate_limit = account.get("rate_limit_per_hour", 20)

    # 计算一小时前的时间戳
    one_hour_ago = datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=1)
    one_hour_ago_str = one_hour_ago.strftime("%Y-%m-%dT%H:%M:%S")

    with _conn() as conn:
        # 过去一小时的调用次数
        result = conn.execute(
            "SELECT COUNT(*) FROM call_logs WHERE account_id=? AND timestamp >= ?",
            (account_id, one_hour_ago_str)
        ).fetchone()
        calls_last_hour = result[0] if result else 0

        # 总调用次数
        result = conn.execute(
            "SELECT COUNT(*) FROM call_logs WHERE account_id=?",
            (account_id,)
        ).fetchone()
        total_calls = result[0] if result else 0

        # 最近一次调用时间
        result = conn.execute(
            "SELECT timestamp FROM call_logs WHERE account_id=? ORDER BY timestamp DESC LIMIT 1",
            (account_id,)
        ).fetchone()
        last_call_time = result[0] if result else None

    return {
        "account_id": account_id,
        "rate_limit_per_hour": rate_limit,
        "calls_last_hour": calls_last_hour,
        "remaining_calls": max(0, rate_limit - calls_last_hour),
        "total_calls": total_calls,
        "last_call_time": last_call_time,
        "is_rate_limited": calls_last_hour >= rate_limit
    }


def update_account_rate_limit(account_id: str, rate_limit_per_hour: int) -> Optional[Dict[str, Any]]:
    """更新账号的速率限制

    Args:
        account_id: 账号 ID
        rate_limit_per_hour: 每小时允许的调用次数

    Returns:
        更新后的账号信息
    """
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET rate_limit_per_hour=?, updated_at=? WHERE id=?",
            (rate_limit_per_hour, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), account_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return _row_to_dict(row) if row else None


def cleanup_old_call_logs(days: int = 7) -> int:
    """清理旧的调用记录

    Args:
        days: 保留最近多少天的记录

    Returns:
        删除的记录数
    """
    cutoff_time = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)
    cutoff_time_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")

    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM call_logs WHERE timestamp < ?",
            (cutoff_time_str,)
        )
        conn.commit()
        return cursor.rowcount


# 初始化数据库
_ensure_db()