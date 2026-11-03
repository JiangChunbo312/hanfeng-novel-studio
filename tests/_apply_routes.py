# -*- coding: utf-8 -*-
"""按实测数据重排角色→模型路由。备份后原子写入 config.local.json。"""
import json
import os
import shutil
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(BASE, "config.local.json")

G = {
    "char":  "volc:doubao-seed-character-260628",
    "mini":  "volc:doubao-seed-2-0-mini-260428",
    "lite":  "volc:doubao-seed-2-0-lite-260428",
    "code":  "volc:doubao-seed-2-0-code-preview-260215",
    "qiniu": "qiniu:qiniu/conatus-free",
    "sense": "senstime:sensenova-6.8-flash-lite",
    "atria": "shusheng:Atria-Dawn",
}
# 不可靠/死模型（实测返回空正文、非合法 JSON、或 403/400）
BAD = [
    "xfyun:spark-x2.6-4b", "shusheng:qwen3.8-27b", "shusheng:Agents-A1",
    "shusheng:Sage-A1.5", "shusheng:intern-s2",
    "volc:kimi-k3-1-pro-261024", "volc:glm-5-2-260617", "volc:glm-5-3-flash-260828",
    "volc:deepseek-v4-flash-ga-260731", "volc:doubao-seed-2-1-turbo-260628",
]

ROUTES = {
    # 写手：创意+长篇，character 最快最优，mini 续航长，qiniu 免费快，sense 文笔好
    "writer":  [G["char"], G["mini"], G["qiniu"], G["sense"], G["lite"], G["code"], G["atria"]],
    # 规划师：创意+结构
    "planner": [G["char"], G["mini"], G["sense"], G["qiniu"], G["lite"], G["code"]],
    # 编排师：轻量整理，求快
    "composer":[G["char"], G["mini"], G["lite"], G["qiniu"], G["code"]],
    # 观察者：必须抽合法 JSON，去掉弱 JSON 的 sense/qiniu
    "observer":[G["char"], G["mini"], G["lite"], G["code"]],
    # 审计员：12 维检查，要合法结构化输出
    "auditor": [G["char"], G["mini"], G["code"], G["lite"]],
    # 修订者：指令跟随+定点改
    "reviser": [G["char"], G["mini"], G["lite"], G["qiniu"], G["sense"]],
    # 摘要：理解+概括，求快
    "summary": [G["char"], G["mini"], G["lite"], G["code"], G["qiniu"]],
    # 默认回落
    "default": [G["char"], G["mini"], G["lite"], G["code"], G["qiniu"], G["sense"]],
}

with open(CFG, encoding="utf-8") as f:
    cfg = json.load(f)

# 备份
bak = CFG + ".bak-1029-" + time.strftime("%H%M%S")
shutil.copyfile(CFG, bak)
print("备份:", bak)

# 写 routes（逗号拼接）
for role, chain in ROUTES.items():
    cfg["routes"][role] = ",".join(chain)

# 写 model_status：好模型 ok，坏模型 bad
status = {k: "ok" for k in set(G.values())}
for b in BAD:
    status[b] = "bad"
cfg["model_status"] = status

# 原子保存（走 config.save 的同款 tmp+replace）
tmp = CFG + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
os.replace(tmp, CFG)
print("已写入新路由与 model_status")

# 打印结果
for role in ["default", "planner", "composer", "writer", "observer", "auditor", "reviser", "summary"]:
    print("%-10s %s" % (role, cfg["routes"][role]))
