# 小红书平价好物带货全自动运营系统 (XHS Supervisor)
# 小红书带货监控系统

一个自动化选品、生成图文、发布小红书笔记的工具。

基于 **Supervisor 多智能体架构** 的全自动运营闭环：

```
API 选品 → AI 图像处理 → 人设文案生成 → RPA 自动挂车发布
```

## 架构

- **Supervisor**：接收初始指令，依据 `AgentState` 的当前语义状态路由到对应 Node。
- **State**：严格的 `AgentState` (TypedDict)，在各 Node 间流转商品信息、图片路径、文案、RPA 执行状态。
- **上下文管理**：`check_and_trim_messages` 截断长 DOM / RPA 日志，防止撑爆上下文窗口。
- **监控**：FastAPI + SSE 流式输出各节点执行日志（兼容 Vercel AI SDK 协议预留）。

## 目录结构

```
xhs-supervisor/
├── .env.example
├── config.toml
├── pyproject.toml
├── src/xhs_supervisor/
│   ├── __init__.py
│   ├── config.py
│   ├── state.py
│   ├── supervisor.py
│   ├── retry.py
│   ├── server.py
│   └── nodes/
│       ├── __init__.py
│       ├── selector.py
│       ├── visual.py
│       ├── copywriter.py
│       └── publisher.py
├── assets/
│   ├── backgrounds/
│   └── output/
├── scripts/
│   └── run_pipeline.py
└── tests/
    └── test_state.py
```

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
playwright install chromium
uvicorn src.xhs_supervisor.server:app --reload --port 8000
python scripts/run_pipeline.py "找一款租房好用的平价收纳好物"
```

## 监控台 (SSE)

`GET /stream` 返回 SSE 流，每个 Node 的日志以 `data: {...}\n\n` 推送，可直接对接 Vercel AI SDK 的 `useChat` / 自定义 EventSource。

```
GET http://localhost:8000/stream?prompt=找一款平价收纳好物
```

## 风控与合规

- RPA 节点内置随机延迟、人类化滚动、指纹浏览器 CDP 接管。
- `点击挂车商品卡片` 的 DOM 交互为占位符，需根据小红书当前 DOM 结构适配。
- 仅用于学习研究，请遵守平台规则。
