# -*- coding: utf-8 -*-
"""删除死模型 + 真任务空正文模型，避免影响后续工作。备份后原子写入。"""
import json
import os
import shutil
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(BASE, "config.local.json")

DEAD = ["volc:glm-5-2-260617", "volc:glm-5-3-flash-260828",
        "volc:deepseek-v4-flash-ga-260731", "volc:doubao-seed-2-1-turbo-260628",
        "volc:kimi-k3-1-pro-261024"]
EMPTY = ["xfyun:spark-x2.6-4b", "shusheng:qwen3.8-27b", "shusheng:Agents-A1",
         "shusheng:Sage-A1.5", "shusheng:intern-s2"]
TO_DEL = set(DEAD + EMPTY)

with open(CFG, encoding="utf-8") as f:
    cfg = json.load(f)

bak = CFG + ".bak-1029-" + time.strftime("%H%M%S")
shutil.copyfile(CFG, bak)
print("备份:", bak)

removed_models = []   # (provider_id, model)
dropped_providers = []

# 1) 从 provider 模型字段删除
new_providers = []
for p in cfg["providers"]:
    pid = p["id"]
    models = [m.strip() for m in str(p.get("model") or "").split(",") if m.strip()]
    keep = []
    for m in models:
        if (pid + ":" + m) in TO_DEL:
            removed_models.append((pid, m))
        else:
            keep.append(m)
    p["model"] = ",".join(keep)
    if keep:
        new_providers.append(p)
    else:
        dropped_providers.append(pid)
cfg["providers"] = new_providers

# 2) routes 兜底清理（防止任何残留）
for k, v in cfg["routes"].items():
    tokens = [t.strip() for t in str(v).split(",") if t.strip() and t.strip() not in TO_DEL]
    cfg["routes"][k] = ",".join(tokens)

# 3) model_status 清理
if "model_status" in cfg:
    cfg["model_status"] = {k: v for k, v in cfg["model_status"].items() if k not in TO_DEL}

# 4) prices 清理
if "prices" in cfg:
    cfg["prices"] = {k: v for k, v in cfg["prices"].items() if k not in TO_DEL}

# 原子保存
tmp = CFG + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
os.replace(tmp, CFG)

print("已删除模型 %d 个:" % len(removed_models))
for pid, m in removed_models:
    print("  -", pid + ":" + m)
print("整服务商移除（模型清空）:", dropped_providers)
print()
print("=== 清理后 providers ===")
for p in cfg["providers"]:
    print(p["id"], "->", p.get("model"))
print()
print("=== 清理后 model_status ===")
for k, v in sorted(cfg["model_status"].items()):
    print(" ", k, v)
