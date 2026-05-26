# coros-ai-coach — 高驰AI教练

[English](README.md)

让你的 AI 助手直接访问 COROS Training Hub 全部数据：睡眠分析、HRV 趋势、训练负荷、课表创建、训练计划导入、日历管理——全程自然语言交互。

无需 API Key，无需官方授权。你的账号密码只留在本地，加密存储在系统钥匙串中。服务器直接与 COROS 通信，使用和官方 Web 应用、手机 App 完全相同的接口。

## 关于本项目

**coros-ai-coach（高驰AI教练）** 是一个 MCP（Model Context Protocol）服务器，在 AI 助手和 COROS Training Hub 之间架起桥梁。它将 COROS 的非官方 API（即 COROS Web 应用和手机 App 使用的那些接口）封装为 25 个 MCP 工具，任何 AI 助手都能直接调用。

市面上大多数 COROS MCP 服务器只做到基础数据拉取（睡眠、HRV、活动列表）。coros-ai-coach 在此基础上做了大幅扩展：

- **训练计划库** — 浏览并导入 200+ 个由 COROS 教练和精英运动员创建的官方训练项目。支持按运动类型、难度、类别筛选，覆盖三个区域（中国/美国/欧洲），完整国际化。
- **课表构建器** — 创建跑步课表，支持 3 种心率区间模型（最大心率/%HRR/%LTHR）、配速目标、功率、步频、等强配速。骑行课表支持功率区间。力量训练支持 COROS 官方动作库。全部支持间歇/循环训练。
- **日历管理** — 训练日历的完整增删改查：查看、安排、改期、删除。外加聚合训练量摘要。
- **每日健康** — 步数、卡路里、压力水平，来自手机 API——这些数据在 Training Hub Web API 中拿不到。

服务器使用你的 COROS 账号密码认证（Web 端 MD5 哈希，手机端 AES-128-CBC 加密——密钥从 COROS Android APK 逆向提取）。Token 存储在系统钥匙串中，过期自动刷新。除 COROS 服务器外，任何数据不会离开你的设备。

## 你能做什么

用自然语言向 AI 助手提问：

- *"我这周的睡眠怎么样？按深睡、REM、浅睡分别统计。"*
- *"过去四周的 HRV 趋势如何？高于还是低于基线？"*
- *"从 COROS 训练库里找一个适合初学者的 10 公里训练计划，帮我导入。"*
- *"创建一个 60 分钟的二区心率跑，包含 10 分钟热身和 5 分钟冷身。"*
- *"把这个课表安排到周四，周五原有的训练挪到周六。"*
- *"显示我最近一个月的训练负荷比——有没有过度训练？"*
- *"给我建一个核心力量循环：平板支撑、卷腹、抬腿，3 组。"*
- *"我当前的乳酸阈值心率和配速是多少？"*
- *"最近练得怎么样？状态能比赛吗？"*
- *"今天该上强度还是该休息？"*

## 与原版的区别

本项目 fork 自 [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp)，在其基础上增加了大量功能。原版仅覆盖基础的睡眠和活动数据获取，coros-ai-coach 新增：

| 领域 | 原版 | coros-ai-coach |
|------|------|----------------|
| 每日健康 | — | 步数、卡路里、压力水平（手机 API） |
| 训练库 | — | 浏览 200+ 官方项目，一键导入 |
| 跑步课表 | — | 完整心率区间构建器 — 3 种模型（最大心率/%HRR/%LTHR）、配速、功率、步频 |
| 力量训练 | — | 基于 COROS 动作库的循环训练构建器 |
| 日历 | 仅查看 | 查看、安排、改期、删除、训练量摘要 |
| 仪表盘 | — | 快速"今天状态如何？"快照 |
| 用户资料 | — | 心率区间、配速区间、功率区间、生理基线 |
| 课表管理 | 创建/列出 | 创建、列出、删除课表 AND 训练计划 |
| 训练库浏览 | — | 按运动、难度、类别、区域、语言筛选 |

## 工具列表

### 健康与状态

| 工具 | 说明 |
|------|------|
| `get_dashboard` | 当前 HRV、睡眠质量、准备状态、近期活动摘要、体能趋势。无需日期参数——始终返回最近约 7 天数据。 |
| `get_daily_health` | 每日步数、卡路里、压力水平（均值+时长）、睡眠阶段分布。来自手机 API——Training Hub 中拿不到的数据。 |
| `get_sleep_data` | 每晚睡眠阶段（深睡、浅睡、REM、清醒）、午睡、睡眠心率（均值/最低/最高）、质量评分。支持 1–52 周。 |
| `get_user_profile` | 全部生理基线：最大心率、静息心率、乳酸阈值心率、乳酸阈值配速、FTP。3 种模型的心率区间、配速区间、骑行功率区间。 |

### 训练分析

| 工具 | 说明 |
|------|------|
| `get_training_analysis` | 完整的 COROS「数据分析」报告。35 项每日指标：HRV（RMSSD + 基线）、静息心率、训练负荷（日/急性/慢性）、疲劳率、VO2max、体能、表现指数。周度摘要及推荐负荷范围。按运动类型分布统计。强度分布。个人纪录。支持 1–24 周。 |

### 活动

| 工具 | 说明 |
|------|------|
| `list_activities` | 分页活动列表：运动类型、时长、距离、心率、功率、卡路里、训练负荷、爬升。 |
| `get_activity_detail` | 完整活动详情：分圈数据、心率区间、功率区间、全部运动专项指标。 |
| `list_sport_types` | 所有 COROS 运动类型 ID 及名称——创建课表时的有用参考。 |

### 课表构建器

| 工具 | 说明 |
|------|------|
| `create_run_workout` | 跑步课表，支持心率区间目标（1–6 区）。三种区间模型：最大心率、%HRR（储备心率）、%LTHR（乳酸阈值）。同时支持配速目标（秒/公里）、功率（瓦特）、步频（步/分钟）、等强配速。支持间歇循环。 |
| `create_workout` | 骑行课表，支持功率目标（瓦特）。默认室内骑行，支持公路车。支持间歇/循环。 |
| `create_strength_workout` | 力量循环训练。动作来自 COROS 动作库（先用 `list_exercises` 浏览）。可配置组数、次数或计时目标、休息间隔。 |
| `list_exercises` | 力量/体能训练的 COROS 动作库。每个动作包含 `origin_id`、T-code 名称和 `sid_` 概览键。 |

### 训练库

| 工具 | 说明 |
|------|------|
| `get_training_library` | 浏览 COROS 公开训练库：200+ 由 COROS 教练和运动员创建的项目。每个条目包含标题、描述、运动类型、难度等级、训练目标、作者和下载量。支持按运动类型、难度、类别筛选。可选区域（中国/美国/欧洲）和语言（中文/英文/德文等）。 |
| `import_training_program` | 一键将训练库项目导入个人账户。自动将内部代码解析为可读名称。适用于单次课表和多周训练计划。 |

### 日历

| 工具 | 说明 |
|------|------|
| `list_planned_activities` | 训练日历上某日期范围内的全部已安排内容。 |
| `schedule_workout` | 将课表库中的训练安排到特定日期。 |
| `remove_scheduled_workout` | 从日历中移除已安排的训练。 |
| `get_training_summary` | 某日期范围内的聚合训练量（时长、负荷、次数）。比列出全部活动更轻量。 |

### 课表与计划管理

| 工具 | 说明 |
|------|------|
| `list_workouts` | 账户中所有已保存的课表和训练计划。包含结构预览：步骤、时长、强度目标。 |
| `delete_workout` | 删除课表。 |
| `delete_plan` | 删除训练计划。 |

### 智能教练

| 工具 | 说明 |
|------|------|
| `get_coach_briefing` | 智能教练简报。一次调用，无需手动编排。内部并行拉取 6 个数据源，运行 10 项专业分析（基于 TrainingPeaks PMC、Coros EvoLab 和 2025 耐力教练共识）。返回准备度评分（0-5）、疲劳水平、训练状态、HRV 趋势、睡眠分析、今日训练建议（含强度/时长/证据链）、周度负荷对比、体能趋势、预警信号（HRV 下降、睡眠债、过度训练风险、长期未训练）。只需问一句"最近练得怎么样？" |

### 认证

| 工具 | 说明 |
|------|------|
| `authenticate_coros` | 邮箱 + 密码登录。同时存储 Web 和手机 Token。 |
| `authenticate_coros_mobile` | 仅手机端登录（睡眠 + 每日健康数据）。 |
| `check_coros_auth` | Token 有效性状态、过期时间、手机 Token 状态。 |

## 架构

### 双 API 设计

COROS 将数据分布在两套独立的 API 系统中：

| | Training Hub（Web） | Mobile API |
|---|---|---|
| **主机** | `teameuapi.coros.com`（欧洲）/ `teamapi.coros.com`（美国） | `apieu.coros.com`（欧洲）/ `api.coros.com`（美国） |
| **认证** | MD5 哈希密码 → `accessToken` 请求头 | AES-128-CBC 加密凭证（密钥从 COROS APK 逆向） |
| **Token 有效期** | ~24 小时 | ~1 小时 |
| **刷新方式** | 用存储的凭证重新认证 | 重放存储的加密登录载荷 |
| **数据** | HRV、训练指标、活动、课表、日历 | 睡眠阶段、步数、卡路里、压力 |

`get_training_analysis` 更进一步：它并行调用两个 Training Hub 端点（`/analyse/dayDetail/query` 获取可配置日期范围的数据 + `/analyse/query` 获取 VO2max/体能字段），并合并为统一结果。

### Token 存储

读取优先级链：`COROS_ACCESS_TOKEN` 环境变量 → 系统钥匙串（Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service）→ AES-256-GCM 加密本地文件。

写入时同时更新钥匙串和加密文件。完整的 `StoredAuth` 对象——Web Token、手机 Token、用于重放的手机登录载荷——序列化为 JSON，作为单个凭据存储。

### 自动认证

如果设置了 `COROS_EMAIL` 和 `COROS_PASSWORD`（通过 `.env` 或环境变量），服务器在首次请求时自动认证，Token 过期或被拒绝时自动重新认证。无需手动操作。

## 安装配置

### 1. 安装

```bash
git clone https://github.com/Ericyuanxiang/coros-ai-coach.git
cd coros-ai-coach
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. 配置

在项目目录创建 `.env` 文件：

```env
COROS_EMAIL=you@example.com
COROS_PASSWORD=yourpassword
COROS_REGION=eu
```

有效区域：`eu`、`us`、`cn`。服务器首次使用时自动认证。

### 3. 验证

```bash
coros-ai-coach test
```

一键检查 Python 版本、依赖、认证状态和 API 连通性。

### 4. 注册到 Claude Code

```bash
claude mcp add coros -- /path/to/coros-ai-coach/.venv/bin/coros-ai-coach serve
```

或在 `claude_desktop_config.json` 中：

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-ai-coach/.venv/bin/coros-ai-coach",
      "args": ["serve"]
    }
  }
}
```

### 手动认证（可选）

如果不使用 `.env` 文件：

```bash
coros-ai-coach auth          # 交互式登录 — 存储 Web + 手机 Token
coros-ai-coach auth-status   # 查看过期时间和 Token 状态
coros-ai-coach auth-clear    # 清除所有已存储的 Token
```

## 环境要求

- Python >= 3.11
- 一个 COROS 账号（支持所有区域：欧洲、美国、亚洲/中国）

## 依赖

- [fastmcp](https://github.com/jlowin/fastmcp) — MCP 服务器框架
- [httpx](https://www.python-httpx.org/) — 异步 HTTP 客户端
- [pycryptodome](https://pycryptodome.readthedocs.io/) — 手机 API 认证的 AES 加密
- [keyring](https://github.com/jaraco/keyring) — 跨平台凭据存储
- [pydantic](https://docs.pydantic.dev/) — 数据验证与序列化
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` 文件支持

## 项目结构

```
coros-ai-coach/
├── server.py           # FastMCP 工具定义（25 个工具）
├── coros_api.py        # HTTP 客户端、双 API 认证、AES 加密、响应解析
├── coach.py            # 教练分析引擎（准备度、疲劳度、训练状态、训练建议）
├── models.py           # Pydantic v2 数据模型
├── cli.py              # CLI 入口（serve、auth、test）
├── auth/               # Token 存储：钥匙串 + AES-256-GCM 加密文件回退
└── pyproject.toml
```

## 常见问题

| 问题 | 解决方法 |
|------|----------|
| **"未认证"** | 运行 `coros-ai-coach test` 验证 `.env` 凭据。如果没有 `.env`，运行 `coros-ai-coach auth` 交互登录。 |
| **认证失败 / 区域错误** | 检查 `.env` 中的 `COROS_REGION`。必须为 `eu`、`us` 或 `cn`。EU 的 Token 不能用于 US/CN 服务器，反之亦然。 |
| **手机 API 不可用（无睡眠数据）** | 某些区域可能无法使用手机 API。运行 `coros-ai-coach auth-mobile` 重试。睡眠数据为尽力提供。 |
| **Token 频繁过期** | Web Token 有效期约 24 小时，会自动刷新。如频繁遇到认证错误，请检查系统时间是否准确。 |
| **Linux 密钥环错误** | 安装 `dbus-python` 或 `secretstorage`。不可用时服务器会自动回退到 AES-256-GCM 加密本地文件。 |
| **Claude Code 中找不到工具** | 注册 MCP 服务器后重启 Claude Code。先运行 `coros-ai-coach test` 确认服务器可独立运行。 |
| **启动时报 ImportError** | 运行 `pip install -e .` 重新安装依赖。用 `python --version` 确认 Python >= 3.11。 |

## 致谢

Fork 自 [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp)（MIT License）。
