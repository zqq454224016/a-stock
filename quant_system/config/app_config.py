"""Local application configuration backed by config/local.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "local.json"


def load_app_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"配置文件无效: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"配置文件根节点必须是对象: {path}")
    return data


def tickflow_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    section = load_app_config(path).get("tickflow") or {}
    if not isinstance(section, dict):
        raise RuntimeError("配置项 tickflow 必须是对象")
    return {
        "api_key": str(section.get("api_key") or "").strip(),
        "base_url": str(section.get("base_url") or "").strip(),
    }


def tushare_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    section = load_app_config(path).get("tushare") or {}
    if not isinstance(section, dict):
        raise RuntimeError("配置项 tushare 必须是对象")
    return {"token": str(section.get("token") or "").strip()}


def feishu_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    section = load_app_config(path).get("feishu") or {}
    if not isinstance(section, dict):
        raise RuntimeError("配置项 feishu 必须是对象")
    return {"webhook_url": str(section.get("webhook_url") or "").strip()}


def save_tickflow_config(api_key: str, base_url: str = "", path: Path = CONFIG_PATH) -> Path:
    data = load_app_config(path)
    data["tickflow"] = {"api_key": api_key.strip(), "base_url": base_url.strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


def save_data_source_config(
    *, tickflow_api_key: str | None = None, tickflow_base_url: str | None = None,
    tushare_token: str | None = None, path: Path = CONFIG_PATH,
    feishu_webhook_url: str | None = None,
) -> Path:
    data = load_app_config(path)
    if tickflow_api_key is not None or tickflow_base_url is not None:
        previous = data.get("tickflow") if isinstance(data.get("tickflow"), dict) else {}
        data["tickflow"] = {
            "api_key": (tickflow_api_key if tickflow_api_key is not None else previous.get("api_key") or "").strip(),
            "base_url": (tickflow_base_url if tickflow_base_url is not None else previous.get("base_url") or "").strip(),
        }
    if tushare_token is not None:
        data["tushare"] = {"token": tushare_token.strip()}
    if feishu_webhook_url is not None:
        data["feishu"] = {"webhook_url": feishu_webhook_url.strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path
