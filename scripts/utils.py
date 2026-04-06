#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数
"""
import json
import logging
import subprocess
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def _run_lark_cli_api(as_identity: str, method: str, path: str,
                      params: Optional[Dict] = None,
                      data: Optional[Dict] = None) -> Dict[str, Any]:
    cmd: List[str] = ["lark-cli", "--as", as_identity, "api", method, f"/open-apis/{path}"]

    if params:
        cmd.extend(["--params", json.dumps(params, ensure_ascii=False)])

    if data:
        cmd.extend(["--data", json.dumps(data, ensure_ascii=False)])

    logger.debug(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        response = json.loads(result.stdout)
        logger.debug(f"API 响应: {response}")
        return response

    except subprocess.CalledProcessError as e:
        logger.error(f"lark-cli 命令执行失败: {e}")
        raise Exception(f"API 调用失败: {e.stderr}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}")
        raise Exception(f"响应解析失败: {e}")


def run_lark_cli_as_bot(method: str, path: str, params: Optional[Dict] = None,
                        data: Optional[Dict] = None) -> Dict[str, Any]:
    """以 bot 身份执行 lark-cli api（等价于 lark-cli --as bot api ...）。"""
    return _run_lark_cli_api("bot", method, path, params, data)


def run_lark_cli_as_user(method: str, path: str, params: Optional[Dict] = None,
                         data: Optional[Dict] = None) -> Dict[str, Any]:
    """以 user 身份执行 lark-cli api（等价于 lark-cli --as user api ...）。"""
    return _run_lark_cli_api("user", method, path, params, data)


def get_lark_cli_auth_user_open_id() -> Optional[str]:
    """
    执行 `lark-cli auth list`，解析当前登录用户的 open_id（JSON 中的 userOpenId）。
    用于日历「添加参会人」等需指定操作人 user_id 的场景。
    """
    cmd = ["lark-cli", "auth", "list"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("lark-cli auth list 执行失败: %s", e.stderr or e)
        return None
    except OSError as e:
        logger.warning("无法执行 lark-cli auth list: %s", e)
        return None

    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("lark-cli auth list 输出不是合法 JSON: %s", e)
        return None

    entries: List[Any]
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        inner = data.get("items") or data.get("data") or data.get("auths")
        entries = inner if isinstance(inner, list) else [data]
    else:
        return None

    for item in entries:
        if not isinstance(item, dict):
            continue
        oid = item.get("userOpenId") or item.get("user_open_id")
        if oid:
            return str(oid).strip()
    return None
