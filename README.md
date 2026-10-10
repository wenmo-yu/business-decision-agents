# 多智能体经营决策平台

这是一个面向品牌/平台招商运营团队的多智能体经营决策平台。它将**经独立问数服务校验的经营事实**、公开市场情报、内部经营资料和用户附件汇聚为一份可追溯的增长诊断与行动建议。

它刻意不重复实现 Text-to-SQL：已有的「电商智能问数 Agent」专注自然语言到安全 SQL、Schema 混合检索与只读执行；本平台通过受控 HTTP 合约消费它的结果，负责跨源取证、归因、证据审查和报告交付。

## 产品闭环

```text
经营问题
  ├─ 市场情报助手：竞品 / 平台规则 / 舆情 / 行业趋势
  ├─ 经营问数助手：调用独立问数服务，取得已校验的业务事实
  ├─ 经营知识助手：SOP / 活动复盘 / 品类策略 / 上传附件
  └─ 证据审查助手：完整度、时效、来源覆盖与待验证项
                         ↓
             诊断归因、策略建议、Markdown / PDF 报告
```

## 界面预览

![多智能体经营决策平台：从任务拆解、跨源证据到行动建议的决策工作台](docs/showcase/dashboard-preview.png)

> 预览图为静态产品原型，用于展示核心交互与信息架构；运行中的界面会实时展示子智能体调用、证据事件和报告产物。

## 与「电商智能问数 Agent」的边界

| 能力 | 电商智能问数 Agent | 多智能体经营决策平台 |
| --- | --- | --- |
| 目标 | 回答“指标是多少、按什么维度变化” | 回答“为什么发生、应做什么、证据是否充分” |
| 数据访问 | Schema 检索、SQL 生成/校验、只读执行 | 仅调用问数服务，不连接业务库、不生成 SQL |
| 核心技术 | LangGraph、Qdrant、Elasticsearch、MySQL | DeepAgents 多智能体、FastAPI、WebSocket、Tavily、自建 Hybrid RAG、证据规则引擎 |
| 产物 | 可审计的数据答案 | 跨源证据链、增长诊断、行动清单、Markdown/PDF 报告 |

## 多智能体设计

- **市场情报助手**：采集竞品动作、平台规则、行业趋势和公开用户反馈，保留 URL 与发布时间。
- **经营问数助手**：调用已部署的问数服务，要求返回指标口径、时间范围、执行状态与 SQL 审计摘要；服务边界确保本项目没有直接 SQL 执行能力。
- **经营知识助手**：从平台自建 Hybrid RAG 检索企业内部策略、活动复盘和商品资料；每条证据保留文件名、分块编号和融合分数。
- **证据审查助手**：在出结论前用确定性规则检查来源类型、URL、时间范围和缺失证据，避免“有结论无依据”。
- **编排主智能体**：负责假设拆解、选择性路由、归因和报告生成；不把不充分的证据表述为事实。

## 内置 Hybrid RAG

知识库不依赖 RAGFlow 或第三方 RAG 平台，由应用自身维护完整链路：

```text
PDF / DOCX / Markdown / TXT
        ↓ 文档解析与重叠分块
OpenAI 兼容 Embedding → SQLite 持久化向量
        ↓                         ↓
中文字符 n-gram + SQLite FTS5 / BM25 词法召回 ← 语义余弦召回
        ↓
基于排名的 Reciprocal Rank Fusion（RRF）融合排序
        ↓
来源文件、分块编号、原文证据、融合分数
```

将内部资料放入任意目录后建立索引：

```bash
uv run python -m app.rag.indexer docs/knowledge_base
```

索引默认保存在 `app/data/knowledge.db`，已被 `.gitignore` 排除。通过 `RAG_DB_PATH` 可改为部署环境中的持久化路径；通过 `RAG_EMBEDDING_MODEL` 指定 OpenAI 兼容的嵌入模型。中文文本在入库和查询两端统一生成单字和双字 n-gram，避免 `unicode61` 把连续中文当作单一 token；词法与语义候选分别按各自排名进入 RRF，因此不会对 FTS5 的负向 BM25 原始分数做错误归一化。

RRF 仅用于排序，不作为“可回答置信度”。当没有词法命中且最优语义相似度低于 `RAG_MIN_SEMANTIC_SCORE`（默认 `0.35`）时，知识助手会返回“证据不足”。索引还记录 Embedding 模型和向量维度；两者变更时会拒绝混用旧向量，要求重建索引。

用户上传附件会自动建立独立的会话级索引，位于 `app/data/sessions/{thread_id}.db`。知识助手只合并全局知识库和当前会话索引，不会检索其他会话附件。

## 问数服务集成

默认对接现有问数项目的 SSE 接口：

```text
POST {ECOM_ANALYTICS_API_URL}/api/query
```

请求体：

```json
{"query": "近 30 天女装品类 GMV 与转化率变化", "session_id": "当前会话 ID"}
```

适配器会收集 SSE 事件，并对事件内的数据结构做有界截断，保证返回内容始终是合法 JSON；SSE 中的 `error` 事件会被判定为失败，不能作为经营事实使用。当前 SSE 协议未提供标准化的最终结果、时间范围或 SQL 审计字段，因此适配器会明确标记该限制。

当问数项目新增 JSON 汇总端点后，可设置 `ECOM_ANALYTICS_PROTOCOL=json`，并实现 `POST /api/analytics/query`，返回 `data`、`execution_status`、`metric_definition`、`time_range`、`sql_audit` 与 `limitations`。无论哪种协议，平台均不透传或执行 SQL。

## 本地启动

1. 安装后端：`uv sync`
2. 复制 `.env.example` 为 `.env`，配置模型、Tavily、内置 Hybrid RAG 的 Embedding 模型和问数服务地址。
3. 启动 API：`uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload`
4. 启动前端：`cd frontend && pnpm install && pnpm dev`

可尝试：

```text
分析近 30 天女装品类 GMV 下滑的可能原因：先查询经营数据，再检索主要竞品促销与平台规则变化；给出证据链、优先级排序的行动建议和待验证项，并生成 Markdown 报告。
```

## 后续演进

1. 用 PostgreSQL 持久化任务、证据、报告版本和人工复核记录。
2. 用 Redis 队列承载长任务、重试与并发限制。
3. 增加指标异常检测、策略实验记录与报告评测集。
4. 增加角色权限、组织隔离、文件安全扫描和审计日志。

## Acknowledgements

本项目的早期多智能体研究原型参考了 [didilili/deepsearch-agents](https://github.com/didilili/deepsearch-agents)。本项目已围绕电商增长情报场景，独立重构了产品定位、智能体协作边界、问数服务适配、证据审查机制与交互文案。

> 原仓库未明确展示许可证；公开发布本项目之前，请确认原作者授权范围，或将保留的原始实现进一步替换为独立实现。
