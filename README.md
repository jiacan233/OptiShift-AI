# OptiShift

**AI Scheduling Agent + Deterministic Scheduling Solver**

OptiShift 是一个“单门店共享排班工作区 + 服务端持久化 AI Scheduling Agent”。员工、规则和排班属于同一个共享工作区；每个浏览器通过匿名 `browser_workspace_id` 拥有自己的多轮对话和历史记录。Agent 负责理解、分析和选择受控工具，OR-Tools CP-SAT 与独立 Validator 负责排班和业务约束。

**Repository:** [github.com/jiacan233/OptiShift-AI](https://github.com/jiacan233/OptiShift-AI)

## Live Demo

[https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com](https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com)

## Architecture

```mermaid
flowchart LR
  User[User Message] --> Parser[LLM Semantic Parser]
  Parser --> Plan[Typed TurnCommand / TurnPlan]
  Plan --> Grounding[Deterministic Grounding / Validation]
  Grounding --> State[DialogueState / Scenario]
  State --> Solver[CP-SAT Solver]
  Solver --> Validator[Independent Validator]
  Validator --> Draft[Draft]
  Draft --> Confirm[Human Confirm]
  State --> DB[(SQLAlchemy / Alembic)]
```

LLM 只负责自然语言理解、结构化 Intent、引用解析和回答组织。它不会直接执行 SQL、写 Repository、运行 Solver、绕过版本检查或确认正式排班。所有写操作都经过确定性 Action Gate；只有 `generate` 和 `replan` 可以创建 Draft，正式生效始终要求用户点击“确认变更”。

## Tech Stack

- Frontend: React, Vite, TypeScript, Tailwind CSS
- Backend: FastAPI, Pydantic
- Optimization: Google OR-Tools CP-SAT
- Persistence: SQLAlchemy 2.x, Alembic, SQLite (local), CloudBase MySQL (production)
- Packaging: single-service Docker image

## Local Setup

需要 Python 3.11+ 与 Node.js 20+。

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
uvicorn backend.app.main:app --reload --port 8000
```

API 默认地址为 `http://localhost:8000`，健康检查为 `GET /health`。

### Frontend development server

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。Vite 开发服务器把 `/api` 请求转发到 FastAPI。

## Docker Run

```powershell
docker compose up --build
```

浏览器打开 `http://localhost:8080`。本地 Docker Compose 使用 SQLite，并把数据保存在命名卷 `optishift-data` 中。

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | `development` or `production`; production requires MySQL | `development` |
| `DATABASE_URL` | SQLAlchemy URL for SQLite or MySQL | `sqlite:///./data/optishift.db` |
| `PORT` | HTTP listening port used by CloudBase Run | `8080` |
| `LLM_ENABLED` | Enable free-form Structured Output routing and response composition | `false` |
| `LLM_API_KEY` | OpenAI-compatible provider key | empty |
| `LLM_MODEL` | Router/composer model | `gpt-4.1-mini` |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.openai.com/v1` |
| `LLM_READ_TIMEOUT_SECONDS` | Provider read timeout | `120` |
| `LLM_HEALTH_READ_TIMEOUT_SECONDS` | AI health probe read timeout | `30` |
| `CORS_ORIGINS` | Local frontend origins | localhost Vite origins |
| `SOLVER_MAX_TIME_SECONDS` | CP-SAT time limit | `10` |
| `SOLVER_RANDOM_SEED` | Deterministic seed | `42` |

## Data Model

- **Employee:** stable ID, role, master-data skills, available days, leave days, preferred shift.
- **Schedule:** schedule ID, version, parent/base relationship, Monday `week_start`, assignments, status and timestamp.
- **Conversation:** anonymous browser workspace ownership, title, summary, active/archived status and timestamps. A conversation can span multiple weeks.
- **Conversation Message:** persisted user/assistant content, structured intent, mutation flag, resolved target week, schedule/version reference and audited metadata.
- **Agent Tool Call:** persisted tool name, deterministic input/output summary, status and timestamps. Chain of thought is never stored.
- **Scheduling Context:** base schedule, employee snapshot, rules, requested changes and previous-week history state (`known_empty`, `available`, or `unavailable`).

## Browser Workspace and Conversation History

首次访问时，前端生成随机 `browser_workspace_id` 并仅把该 ID 与当前 `conversation_id` 保存到 `localStorage`。聊天正文、工具结果和排班副本不会写入浏览器存储，刷新或打开历史对话时均从服务端数据库恢复完整消息。

Conversation 创建后绑定当前 Browser Workspace。列表和详情接口同时校验 `browser_workspace_id`，所以一个浏览器不能列出或读取另一个浏览器的匿名对话。这是 Demo 阶段的浏览器级隔离，不是用户认证、租户边界或权限系统。

每条用户消息携带 `client_message_id`。网络失败后的 Retry 复用同一个 ID；服务端按 `(conversation_id, client_message_id)` 返回首次完成的结果，不会再次生成 Draft 或重复调用 Solver。同一 Conversation 的 turn 由带 owner token 的数据库租约串行执行；进程在 Draft 写入后中断时，服务端会按草稿来源标记恢复首次结果，即使该草稿随后已确认或取消，也不会把同一用户动作重新执行一遍。

## ISO Week and Schedule Context

界面使用标准 ISO 8601 自然周（周一到周日）展示和解析周次，数据库仍以 Monday `week_start` 作为 Schedule key。例如 `2026年第40周` 解析为 `2026-09-28`。自然语言日期和相对周次由 LLM 归一为周一日期；Resolver 只验证结构化日期，并在未指定时选择可信操作、建议引用、工作台、历史目标周或当前周。

每周独立恢复三种状态：

- `display_schedule`：该周有 Draft 时展示 Draft，否则展示 Confirmed。
- `confirmed_schedule`：该周真正生效的正式版本。
- `mutation_base`：Replan 使用的最新 Confirmed ID/version，绝不使用正在展示的 Draft。

版本历史也按目标周加载。切换上一周、下一周或直接选择周次时，Schedule Grid、版本记录和 Agent 当前上下文会同步更新。

## Database and Migrations

本地开发使用 SQLite，生产环境通过同一个 `DATABASE_URL` 使用 CloudBase MySQL。Repository 只维护一套 SQLAlchemy ORM 业务逻辑；`APP_ENV=production` 时若未配置 MySQL，应用会明确启动失败，不会回退到容器内 SQLite。

从空数据库创建完整 Schema：

```powershell
alembic upgrade head
python -m backend.app.scripts.seed_demo
```

Seed 是幂等的：只补充缺失的 Demo 员工，不覆盖已有员工资料，也不会创建重复记录。

## Hard Constraints

| ID | Rule |
|---|---|
| H01 | 每名员工每天最多一个班次 |
| R01 | 每班至少 1 名具备 `manager` 技能的员工 |
| R02 | 每班至少 2 名具备 `beverage` 技能的员工 |
| R03 | 每班至少 1 名具备 `cashier` 技能的员工 |
| R04 | 工作日每班至少 4 人，周末每班至少 6 人 |
| R05 | 每名员工每周最多 5 个班次 |
| R06 | 不得连续工作超过 5 天，包含跨周边界 |
| R07 | 晚班后不得安排次日早班，包含跨周边界 |
| R08 | 请假或不可工作日期不得排班 |
| R09 | 技能仅来自 Employee Master Data |

独立 Validator 只读取最终 Schedule、Employee、Context 与 Rules，不依赖 Solver 内部变量。

### Compliance Status & Force Override Semantics

系统将排班合规状态分为三种明确语义：
- **`compliant`**：所有规则完全满足，标准合规排班。
- **`authorized_violations`**：用户明确授权强制突破特定可放宽规则（仅限 R01、R02、R03、R04 人员/技能覆盖缺口，以及 R08 单个员工指定日期的请假安排），属于用户明确授权的非标准合规方案。工作台展示醒目警告横幅，排班表和日期视图上对违规班次渲染警示标记（如 `⚠ R08 强制安排`），Agent 回复明确声明“这是用户明确授权强制生成的非标准合规方案”并列出具体规则冲突。用户确认时必须通过“确认非合规强制方案”按钮进行显式二次确认，确认后违规项随版本完整留存审计。
- **`invalid`**：存在未授权违规或不可突破的绝对保护规则违规，绝对禁止确认生效。

**不可突破的核心保护规则（Protected Rules）：**
- `H01`（每日最多一个班次）
- `R05`（每周最多 5 班 / 40 小时）
- `R06`（不得连续工作超过 5 天）
- `R07`（上一天晚班后不得安排次日早班）
- `R09`（技能必须来自员工数据，Agent 不得自行补技能）

以上保护规则无论如何强制均绝对保护，不可被任何授权绕过。

## Soft Objectives

- **S01 Preference:** 偏好班次奖励 `+5`。
- **S02 Workload Balance:** 工作量差距惩罚 `-2 × gap`。
- **S03 Minimal Perturbation:** Replan 时相对明确 Base 的变更惩罚 `-8 × changed assignment`。

权重由规则配置提供，硬约束不会因目标函数而放宽。

## Schedule Lifecycle

### Generate

`Generate → CP-SAT → Independent Validate → Draft → Confirm → Confirmed v1`

Generate 永远先创建 draft，不会直接覆盖正式排班。
同一周已经存在 Confirmed 时，再次 Generate 会沿当前 lineage 创建 vN+1，并把当前版本作为显式 Base；不会创建第二条“当前正式排班”分支。

同一目标周已有待确认 Draft 时，Pending Draft Gate 返回 `draft_pending`。系统不会覆盖、取消或并行创建另一个候选 Draft。刷新页面会同时恢复该周的 Confirmed、Pending Draft、Validation、Diff、Impact 和版本记录。

### Replan

Replan 请求必须携带 `base_schedule_id` 与 `base_version`：

`Confirmed vN → Apply contextual changes → Solve → Validate → Diff → Draft vN+1 → Confirmed vN+1`

一次性请假只应用于该次调度上下文，不会静默修改员工永久主数据。

### Version Conflict

Replan 和 Confirm 均在服务端检查乐观版本。若客户端 Base 已过期，API 返回 `version_conflict` 和当前版本，前端要求刷新，不自动 rebase 或覆盖。
Draft 还会记录员工主数据修订号；员工资料在草稿生成后发生变化时，旧草稿会拒绝确认并要求重新生成。

全新数据库第一次排班时会持久化一个明确的 `known_empty` 周边界。之后若中间周缺少已确认排班，服务返回 `history_unavailable`，不会把未知历史当作无人工作。

## Agent Router and Tools

Free-form Chat 使用 OpenAI-compatible `/chat/completions` Structured Output Router，支持：

- `generate`, `replan`: 通过写工具创建 Draft。
- `validate`, `advice`, `explain`, `ask`: 只读分析。
- `clarification`: 信息或引用存在歧义时继续询问。
- `out_of_scope`: 与排班工作区无关的请求。

确定性 Action Gate 不信任模型声明：只有 `generate` 和 `replan` 可以进入写工具。聊天里的“确认”“应用”“就这样”不会调用 Confirm API。Quick Actions 可以携带 trusted structured intent，在 LLM 关闭时仍可直接使用确定性工具链。

工具层提供真实的排班、员工、规则、历史、Validator、分析、Generate 和 Replan 操作。Advice 的建议会记录 `target_week`、`based_on_schedule_id`、`based_on_version` 和 `proposed_changes`。后续“第二条为什么”“按这个改”通过消息 metadata 解析 suggestion 引用；Version Guard 会重新读取最新 Confirmed 和业务数据后再决定是否执行。

自由文本始终由同一个 LLM Semantic Parser 解析为扩展的 `TurnCommand`；Router 只投影这个计划，DialogueAgent 只归约和执行，不再次解释自然语言。员工变更、DAY/SHIFT 人数上下界、目标周、引用、执行许可和本轮 Force 范围均来自这个计划。确定性层校验实体、枚举、原子条件、数量、来源和版本；条件缺失时整批澄清，空 mutation 只修复一次，绝不部分执行。修改请求另经独立 LLM semantic verifier 检查遗漏和授权扩大。

普通可用性陈述默认只记录条件；预演与分析不创建草稿；明确执行才生成待确认草稿。人数约束与员工条件一并传入 Solver、修复试排和独立 Validator。建议绑定来源与依赖快照，过期后必须重新分析。

LLM 关闭、超时或输出畸形时，自由文本安全返回 `AI semantic parser 当前不可用，请重试。`，不会执行猜测的读写操作。Provider 的 JSON Schema/JSON 模式兼容重试仍调用 LLM，不是关键词语义 fallback。可信结构化按钮不需要自然语言解析；确认与取消仍由工作台显式操作。

## INFEASIBLE Diagnosis

无解时不会生成“近似可用”的非法排班。诊断依次执行：

1. **Capacity pre-check**：按班次检查总人数、manager、beverage、cashier 的可用容量。
2. **Diagnostic solver**：只为 R01-R04 引入 staffing slack；H01、R05-R09 保持硬约束。
3. **Candidate blocking analysis**：解释合格候选人是否被 R05、R06、R07 或 R08 阻挡。

诊断求解结果仅用于解释，永远不会保存为正式 Schedule。

## Core API

```text
GET    /health
GET    /api/employees
PATCH  /api/employees/{employee_id}
GET    /api/rules
POST   /api/agent/conversations
GET    /api/agent/conversations?browser_workspace_id=...
GET    /api/agent/conversations/{conversation_id}?browser_workspace_id=...
POST   /api/agent/conversations/{conversation_id}/messages
GET    /api/schedules/week-context?week_start=...
GET    /api/schedules/weeks?anchor_week_start=...
POST   /api/schedule/generate
POST   /api/schedule/replan
POST   /api/schedule/validate
POST   /api/schedule/confirm
POST   /api/schedule/cancel
POST   /api/schedule/explain
GET    /api/schedules/{schedule_id}
GET    /api/schedules/{schedule_id}/versions
```

## Demo Scenarios

1. 切换到 `2026年第40周`，确认日期范围是 `09月28日 - 10月04日`。
2. 询问“你知道我们的项目怎么排班吗？”，获得 AI + Solver 分工说明，排班不发生变化。
3. 询问“第40周有什么优化建议？”，再追问“第二条为什么？”。
4. 发送“按这个改”，经过引用解析、Version Guard 和 Solver 创建待确认 Draft。
5. 再次请求 Mutation，观察 `draft_pending`；在聊天里说“确认”不会让 Draft 生效。
6. 手动点击“确认变更”，再切到第41周生成新 Draft，确认请求使用 `week_start=2026-10-05`。
7. 从“历史”恢复旧 Conversation，刷新页面确认 Conversation 和 Pending Draft 均可恢复。

## Testing

安装后端测试依赖并运行完整测试：

```powershell
pip install -r backend\requirements-dev.txt
python -m pytest -q
```

运行前端静态检查、生产构建和浏览器端验收流程：

```powershell
cd frontend
npm ci
npm run lint
npm run build
npm run test:e2e
```

Playwright 用例覆盖正常生成并确认 v1、E02 周五请假后最小扰动并确认 v2，以及全体店长周日请假时返回可解释冲突且不生成非法草稿。默认使用本机 Chrome channel。

## Deployment

Dockerfile 使用 Node 构建 React 静态资源，并把产物复制到 Python 运行镜像，由 FastAPI 同时提供 API 和前端。容器启动时依次执行 Alembic Migration、幂等 Demo Seed，然后在 `0.0.0.0:$PORT` 启动 FastAPI。

CloudBase Run 使用根目录 Dockerfile、服务端口 `8080` 和 `GET /health` 健康检查。生产环境至少配置：

```env
APP_ENV=production
DATABASE_URL=mysql+pymysql://USER:PASSWORD@INTERNAL_HOST:3306/DATABASE?charset=utf8mb4
PORT=8080
LLM_ENABLED=false
```

CloudBase 服务应连接 MySQL 内网地址并开启与数据库一致的 VPC。Git 部署绑定该仓库的 `main` 分支并开启自动部署；每次 push 会构建同一个单服务镜像并更新相同公网 URL。

## CI

`.github/workflows/ci.yml` 在每次 push 和 pull request 时运行后端测试、前端 lint/build，并在两者通过后验证生产 Docker 镜像能够构建。

## Interview Demo Flow

1. 打开排班工作台，运行“正常生成”，展示班次健康度、10/10 PASS 与员工视角。
2. 确认 v1，运行“E02 临时请假”，说明 Base、Draft、Diff 和 impact radius。
3. 确认 v2，打开版本历史说明 optimistic locking。
4. 运行“周日店长全请假”，展示三层诊断以及无非法 Schedule 生成。
5. 打开员工管理和规则中心，说明技能保护与后端规则单一事实源。


### AI 超时与实时执行进度

Provider 请求统一通过 `AgentLLMClient`，路由、旧版意图解析和说明生成共用应用生命周期内的 HTTP 连接池；服务关闭时先等待流式任务完成，再关闭连接。独立使用客户端时请使用 `with AgentLLMClient()` 或显式 `close()`。

| 环境变量 | 默认秒数 | 作用 |
| --- | ---: | --- |
| `LLM_CONNECT_TIMEOUT_SECONDS` | 8 | DNS、连接、TLS |
| `LLM_READ_TIMEOUT_SECONDS` | 120 | 等待 Provider 响应数据 |
| `LLM_ROUTER_BUDGET_SECONDS` | 60 | Router 所有阶段和兼容重试共用预算，最大 60 秒 |
| `LLM_SEMANTIC_BUDGET_SECONDS` | 20 | 条件/授权语义提取阶段墙钟预算，最大 30 秒 |
| `LLM_RESPONSE_BUDGET_SECONDS` | 8 | 可选回复组织和说明润色墙钟预算，最大 15 秒 |
| `LLM_SCHEMA_RETRY_BUDGET_SECONDS` | 10 | 明确不支持 strict/schema 时唯一一次兼容重试预算 |
| `LLM_WRITE_TIMEOUT_SECONDS` | 50 | 发送请求 |
| `LLM_POOL_TIMEOUT_SECONDS` | 8 | 等待连接池 |
| `LLM_HEALTH_READ_TIMEOUT_SECONDS` | 30 | AI 健康探针等待响应数据 |
| `SOLVER_MAX_TIME_SECONDS` | 10 | 每次 CP-SAT 求解上限 |
| `AGENT_TURN_TIMEOUT_SECONDS` | 300 | 整轮合作式执行预算 |
| `AGENT_TURN_LEASE_SECONDS` | 360 | 数据库 owner 的 stale lease |

所有秒数必须是有限正数，`0`、负数、文本、`NaN` 和 `inf` 均回退到上述默认值。旧 `LLM_TIMEOUT_SECONDS` 已废弃并被忽略，避免遗留的 5 秒配置继续影响聊天。生产配置由 CloudBase 控制台环境变量注入；不使用 `.env.cloudbase`。

Provider read timeout 不等于 Agent turn timeout：120 秒是底层空闲读取上限，业务请求另受 Router、语义提取、回复组织的较短墙钟预算限制，整轮 300 秒预算供所有阶段共用。健康检查的基础聊天与结构化探针各使用独立的 30 秒预算；每个请求构造自己的 timeout，不修改共享客户端配置。连接、读取和其他网络失败不重试；只有 Provider 明确拒绝 strict/schema 功能时，Router 才在剩余预算内进行一次非 strict 兼容请求，格式错误不会触发这个兼容路径。剩余整轮预算更短时按剩余时间截断，回复组织额外预留结果返回时间。限量后台 HTTP worker 超时后不能执行业务写入，也不能覆盖超时结果。Solver timeout 仍是每次 CP-SAT 求解的 10 秒预算。

日志中的 `llm_complete` / `LLM request failed` 关联脱敏服务标识、模型、阶段、请求 ID、conversation/client message、耗时和错误分类；Router 阶段记录 attempt、retry_reason 与预算。测试观测可读取当前 `ExecutionTrace.provider_requests`，统计真实业务请求次数和结果；其中不保存提示词、密钥或隐藏推理，健康探针应单独统计。

`.env.example` 不代表生产运行时配置。发布前后须读取 CloudBase Run 服务 `optishift-ai` 当前版本的实际 `EnvParams`，核对上表预算变量。更新时先读取现有配置，仅合并需要调整的 timeout/budget key，保留 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`DATABASE_URL`、`APP_ENV` 及其他变量；不得打印或提交 secret。无权限读取或修改时，必须报告生产配置尚未确认，不能以代码默认值代替线上验证。

执行预算在关键阶段和写入前检查，Provider/CP-SAT 按剩余预算缩短等待。不强杀线程或数据库事务；正在进行的网络阶段或事务收尾可能使实际耗时略超过预算。已持久化草稿优先恢复，不因回复失败重新求解。lease 实际值至少为执行预算加 30 秒，每隔最多 15 秒续租；lease 不是 HTTP 超时。

保留 `POST /api/agent/conversations/{id}/messages`。新增 `POST /api/agent/conversations/{id}/messages/stream`，请求字段完全相同，通过 fetch 读取 SSE：

- `execution`：包含事件 ID、阶段操作 ID、turn ID、client_message_id、stage、status、时间戳、耗时和白名单业务事实。
- `heartbeat`：每 10 秒维持连接，不进入聊天历史或时间线。
- `result`：普通 POST 的完整结果；`error`：安全错误码和详情，二者均为流的终点。

阶段包括收到请求、读取员工、理解请求、定位上下文、读取排班、Solver、Validator、说明生成、保存 Draft、生成回复、完成或失败。不可行是确定性业务结果，不等同于网络超时。具体路径仅展示真实执行过的阶段；澄清问题不会伪造 Solver 成功。

断线只移除进度订阅，后台继续执行，并保留客户端请求标识。使用同一 `client_message_id` 重试可恢复最终结果；同一消息正在处理时返回 409。最终时间线随回复和幂等结果在同一事务内保存，刷新后可恢复。流式与普通请求共享 AgentService、Action Gate、lease、版本守卫和 Draft 的来源唯一性约束。进程意外终止时仍使用既有 stale recovery。

Execution Timeline 只保存固定阶段和明确筛选的员工编号、日期、调整类型等事实。事件和日志不记录提示词、请求正文、Authorization、API Key、模型隐藏推理、原始工具异常或堆栈。Provider 错误消息经过脱敏，前端显示中文阶段、错误类型、HTTP 状态和耗时。健康检查仍只有基础聊天和小型结构化探针，并分别展示延迟。

CloudBase 发布沿用 main push 触发的 CI：后端测试、前端 lint/build、浏览器回归、Docker build 后部署。SSE 使用 `no-cache, no-transform` 和 `X-Accel-Buffering: no`；上线仍应确认 CloudBase 公网网关没有缓冲响应，网关自身超时应大于执行预算。心跳不能覆盖网关的硬时限。
