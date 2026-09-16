# OptiShift AI · 智能排班助手

OptiShift AI 是一个面向门店周排班的可解释 Web 应用。它把自然语言或结构化变更转换为经过校验的排班请求，由 OR-Tools CP-SAT 生成排班，再由独立规则校验器验收。所有结果先保存为草稿，只有通过校验且版本仍有效时才能确认。

**Repository:** [github.com/jiacan233/OptiShift-AI](https://github.com/jiacan233/OptiShift-AI)

## Live Demo

CloudBase 公网地址将在首次生产部署和线上验收通过后写入此处。

## Architecture

```mermaid
flowchart LR
  UI[React 工作台] --> API[FastAPI]
  API --> Context[Scheduling Context]
  Context --> Solver[OR-Tools CP-SAT]
  Solver --> Validator[Independent Validator]
  Solver --> Diagnosis[Infeasible Diagnosis]
  Validator --> State[Draft / Confirm / Versions]
  State --> DB[(SQLAlchemy Repository)]
  DB --> Local[(SQLite · Local)]
  DB --> Prod[(CloudBase MySQL · Production)]
```

LLM 仅用于意图解析、实体候选提取和可选的解释润色。员工技能、约束判断和最终排班均来自确定性代码与员工主数据。没有 API Key 时，结构化操作、预设、求解、校验、Diff 和诊断仍可使用。

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
| `LLM_ENABLED` | Enable optional LLM parsing/polish | `false` |
| `LLM_API_KEY` | Optional provider key | empty |
| `LLM_MODEL` | Optional provider model | `gpt-4.1-mini` |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `https://api.openai.com/v1` |
| `LLM_TIMEOUT_SECONDS` | Short fallback timeout | `5` |
| `CORS_ORIGINS` | Local frontend origins | localhost Vite origins |
| `SOLVER_MAX_TIME_SECONDS` | CP-SAT time limit | `10` |
| `SOLVER_RANDOM_SEED` | Deterministic seed | `42` |

## Data Model

- **Employee:** stable ID, role, master-data skills, available days, leave days, preferred shift.
- **Schedule:** schedule ID, version, parent/base relationship, week start, assignments, status and timestamp.
- **Schedule Request:** generate/replan/validate intent, explicit base ID/version, requested changes and minimize-changes flag.
- **Scheduling Context:** base schedule, employee snapshot, rules, requested changes and previous-week history state (`known_empty`, `available`, or `unavailable`).

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

独立 Validator 只读取最终 Schedule、Employee、Context 与 Rules，不依赖 Solver 内部变量。任何硬约束失败的草稿都不能确认。

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

### Replan

Replan 请求必须携带 `base_schedule_id` 与 `base_version`：

`Confirmed vN → Apply contextual changes → Solve → Validate → Diff → Draft vN+1 → Confirmed vN+1`

一次性请假只应用于该次调度上下文，不会静默修改员工永久主数据。

### Version Conflict

Replan 和 Confirm 均在服务端检查乐观版本。若客户端 Base 已过期，API 返回 `version_conflict` 和当前版本，前端要求刷新，不自动 rebase 或覆盖。
Draft 还会记录员工主数据修订号；员工资料在草稿生成后发生变化时，旧草稿会拒绝确认并要求重新生成。

全新数据库第一次排班时会持久化一个明确的 `known_empty` 周边界。之后若中间周缺少已确认排班，服务返回 `history_unavailable`，不会把未知历史当作无人工作。

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

1. **正常生成**：生成完整一周草稿，查看 10/10 硬约束、偏好率与员工视角，然后确认 v1。
2. **E02 周五请假**：基于 confirmed v1 重排，查看 Before/After Diff、影响范围与最小扰动，再确认 v2。
3. **版本冲突**：使用过期 base/version 重排或确认，观察 `version_conflict`。
4. **周日 manager 全部不可用**：Primary Solver 返回 INFEASIBLE，展示 R01 缺口和候选阻挡原因，不出现可确认的非法草稿。
5. **LLM 不可用**：关闭 `LLM_ENABLED`，三个结构化 Preset 和所有确定性功能继续工作。

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
