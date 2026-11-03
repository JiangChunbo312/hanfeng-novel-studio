# -*- coding: utf-8 -*-
"""
全局配置：服务商连接、角色→模型路由、单价表、默认值。

配置文件 config.local.json 只存本机，不进 Git（见 .gitignore）。
"""
import json
import os
import shutil
import threading
from typing import Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.local.json")
EXAMPLE_PATH = os.path.join(ROOT, "config.example.json")

DEFAULT_CONFIG = {
    "providers": [],           # [{id,label,base_url,api_key,model,timeout}]
    "routes": {                # 角色 -> "providerId:modelId"，空表示回落 default
        "default": "",
        "planner": "",
        "composer": "",
        "writer": "",
        "observer": "",
        "auditor": "",
        "reviser": "",
        "summary": "",
    },
    "prices": {},              # "providerId:modelId" -> {"in": 元/百万, "out": 元/百万}
    "defaults": {
        "chapter_words": 2000,
        "temperature_writer": 0.85,
        "temperature_audit": 0.25,
        "recent_summary_count": 5,
        "max_auto_revise": 1,
    },
}

_lock = threading.Lock()


def load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        if os.path.exists(EXAMPLE_PATH):
            shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
        else:
            return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    # 补齐缺失字段，避免旧配置升级后炸掉
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    for k, v in DEFAULT_CONFIG["routes"].items():
        cfg["routes"].setdefault(k, v)
    for k, v in DEFAULT_CONFIG["defaults"].items():
        cfg["defaults"].setdefault(k, v)
    return cfg


def save(cfg: dict) -> None:
    with _lock:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def provider_map(cfg: dict) -> Dict[str, dict]:
    return {p.get("id"): p for p in cfg.get("providers", []) if p.get("id")}
