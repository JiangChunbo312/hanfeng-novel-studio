# 寒峰小说工作台（Hanfeng Novel Studio）

本地优先、零第三方依赖的 AI 小说创作工作台。**Python 标准库跑完一切，不用 `pip install` 任何东西。**

> 这是一个"自带 Key、本地运行"的工具：**所有 API Key 只保存在你自己的电脑上**，本项目不收集、不上传、不读取你的任何 Key。

---

## 🖥️ 在线演示

[点击打开在线演示](web-demo/index.html)（GitHub Pages 上的静态界面预览）

- 演示页复刻了工作台三个页面（写作台 / 项目 / 模型配置）的界面效果
- 数据全部为**静态示例**，不包含任何真实配置与 API Key
- 演示页无法执行 AI 调用——完整功能请克隆本仓库后在本地运行

---

## 🚀 快速开始

### 环境要求

- Python 3.9+（Windows / macOS / Linux 均可）
- 一个 OpenAI 兼容的模型服务商 API Key（DeepSeek / Kimi / 智谱 / 通义 / 火山豆包 / OpenRouter / 本地 Ollama 等任意一家）

### 启动

```bash
# 克隆本仓库
git clone https://github.com/JiangChunbo312/hanfeng-novel-studio.git
cd hanfeng-novel-studio

# 启动（默认 http://127.0.0.1:8787，自动开浏览器）
python server.py

# 自定义端口 / 不开浏览器
python server.py --port 9000 --no-browser
```

Windows 用户也可以直接双击 `start.bat`。

### 第一次使用（5 分钟）

1. **模型配置**页：选一个预设（如 DeepSeek）→ 填你的 API Key → 点「测试连接」→ 在「角色 → 模型」里确认路由 → 保存。
2. **项目**页：新建项目。想直接用现有稿子，就在「章节目录」填绝对路径（例如 `E:/.../搞笑三国/chapters`），**不迁移数据**。
3. **写作台**页：选项目 → 章号 → 按 ① → ⑦ 顺序点。或者勾「一键跑完」让它自己走完前六步。
4. **⑦ 采纳写入**才会真正写进章节文件。AI 永远只做参谋。

---

## ✨ 核心功能

| 页面 | 功能 |
|---|---|
| **写作台** | 七步流水线：生成意图 → 写章 → 审计 → 改写 → 抽事实 → 摘要 → 采纳；支持流式输出、一键跑完、批量连写 |
| **项目** | 建书 / 挂载外部章节目录、编辑设定与卷纲、看世界状态快照、回滚 |
| **模型配置** | 多服务商连接（增删改 + 一键测试）、角色 → 模型路由、故障转移、单价表与成本估算 |

### 七步流水线

```
① 生成意图 → ② 写章 → ③ 审计 → ④ 改写（审计不过才跑） → ⑤ 抽事实 → ⑥ 摘要 → ⑦ 采纳写入
```

- 每道工序**可单独重跑**：审计不过只重跑修订，不推倒整章。
- 支持**夜间批量连写**：逐章自动跑完整流水线，失败章不中断队列，可断点续跑。

---

## 🔐 Key 安全说明

- 你的 API Key 只保存在本机 `config.local.json`（该文件已被 `.gitignore` 排除，**永远不会被提交到 Git**）。
- 前端展示 Key 时用 `***KEEP***` 遮罩，浏览器里看不到原文。
- 本项目是本地服务，**没有任何云端上报**；你的 Key 只会在调用你配置的模型服务商时使用。
- 如果你 fork 或二次发布本仓库，请确保 `config.local.json` 不被提交。

### 配置示例

参照 `config.example.json`：

```json
{
  "providers": [
    {
      "id": "demo",
      "label": "示例 · DeepSeek",
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "",
      "model": "deepseek-chat",
      "timeout": 180
    }
  ],
  "routes": { "default": "demo:deepseek-chat" }
}
```

---

## 📂 目录结构

```
hanfeng-novel-studio/
├── server.py              # HTTP 服务（标准库 http.server，零依赖）
├── core/
│   ├── provider.py        # 模型适配：OpenAI 兼容 + 流式 + 连接测试 + 模型列表
│   ├── router.py          # 角色 → 模型路由
│   ├── cost.py            # Token / 费用台账（usage.jsonl）
│   ├── store.py           # 文件即数据库（md/json 读写、快照、回滚）
│   └── config.py          # 配置读写（config.local.json）
├── agents/
│   ├── base.py            # 提示词外置 + 路由 + 记账
│   └── pipeline.py        # 七道工序，每道可单独重跑
├── prompts/               # ← 全部提示词在这里，改它不用改代码
│   ├── planner.md  writer.md  observer.md
│   └── auditor.md  reviser.md  summary.md
├── web/                   # 零构建前端（原生 HTML/JS/CSS）
├── web-demo/              # 纯静态在线演示页（无后端，可部署 GitHub Pages）
├── projects/              # 每本书一个目录（见下）
├── config.example.json    # 配置模板（不含 Key）
└── config.local.json      # 你的 API Key（已 gitignore，别外传）
```

### 每本书的目录结构

```
projects/<书名>/
├── book.json          # 书名/设定/卷纲/禁忌/单章字数
├── state.json         # 世界状态（权威）
├── ledger.json        # 资源账本
├── hooks.json         # 伏笔池
├── chapters/          # 正文（可指向外部目录）
├── summaries/         # 章节摘要
├── drafts/            # 意图/草稿/审计报告（未采纳）
└── snapshots/         # 状态快照，写崩可回滚
```

---

## 📚 附带示例项目

仓库附带两个示例项目，帮助你快速理解工作台的使用方式：

| 项目 | 说明 |
|---|---|
| `恋综编剧她只想搞钱` | 完整示例：24 章正文 + 全流水线产物（意图/草稿/审计/改写/抽取/摘要），展示长篇工作流 |
| `我专收死局全城等我翻盘` | 单章示例：1 章正文 + 完整流水线产物，展示最小工作流 |

> 示例项目仅用于展示工具效果，版权归作者所有，请勿商用。

---

## 🧪 冒烟测试

```bash
python tests/smoke_test.py
```

用一个假的 OpenAI 兼容服务跑通全流程，不联网不花钱，31 项检查。

---

## ⚠️ 注意事项

- API Key 只存在本机 `config.local.json`，不要提交到任何仓库。
- 服务商 Base URL 以各家官方文档为准，界面里给的预设只是省打字。
- 单价表是估算用，实际账单以服务商为准。
- 本项目为个人创作工具开源分享，请合理使用，勿用于违反服务商条款的用途。

---

## 设计原则

1. **文件优先** —— 所有状态都是你能用记事本打开的文件，工作台只是壳。
2. **提示词外置** —— 全部在 `prompts/*.md`，调优改这里就行，不用碰代码。
3. **每道工序可单独重跑** —— 审计不过只重跑修订，不推倒整章。