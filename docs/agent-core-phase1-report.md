# Agent Core 第一阶段完成报告

日期：2026-09-19。工作分支：main。Solver、Validator 和领域模型代码未修改；没有新增 excess staffing penalty，也没有改变 R04 的下限语义。

## 根因及结构调整

原实现直接接受模型的 `previous_message`，从历史中选取 suggestion，再由 EXPLAIN 优先返回该建议解释。路由没有日期、班次等只读查询结构，当前问题没有转成确定性事实查询，模型还需要自行理解整份排班 JSON。

新增 `ReadQueryPlan`，与 Generate/Replan 等 AgentIntent 主流程分离，包含问题类型、目标周、日期、班次、员工、范围、事实类型、比较、引用和反事实标记。固定问题类型映射到两个分析入口，复用 `get_current_schedule` 和现有工具审计、会话、SSE 基础设施。实现分别放在 read_query、read_analysis、read_response、read_turn，未集中堆入 agent_service。

后端从当前原文校准员工、日期和班次；模型不能决定最终周次、工具名或写操作。非法计划和模型故障可对确定性只读问题降级。具体排班对象优先于历史建议，只有明确引用才解析建议序号；历史不能覆盖当前工作台周次。显式应用场景建议还校验目标周、排班版本和 scenario revision，并将 revision 交给写入接口防止并发覆盖。

## 事实与反事实

默认读取 draft，其次 confirmed；明确指定版本时按版本读取，并在事实中记录实际 schedule_id/version/status/source。未指定班次时分别分析早、晚班。

人数按有效员工的唯一 assignment 计算，最低人数取当前 RuleConfig；技能覆盖来自 Employee 主数据。独立 Validator 使用相同快照、规则和员工重新验证。缺少上周历史时明确标记跨周规则未知，不能宣称全周合规。员工安排、工作量、规则、版本差异和可行性也由后端提供事实。

反事实复制 Schedule 到内存，验证直接移除和每个单人替代方案，返回班次覆盖、全周违规、替代人员、是否多个替代方案及工作量变化。不调用 replan，不写 schedules、不创建草稿、不写 scenario、不确认排班。没有运行全局反事实重求解时，`re_solve_status=not_run`、可行性和 objective delta 为 null，明确不证明唯一必要。独立的可行性问题可在内存中调用现有 CP-SAT。

事实句由确定性代码构造，LLM 通过封闭 ID schema 组织顺序，不能新增、删改数字或技能。模型结果不完整时使用确定性顺序。最终答案说明“当前只是分析，没有修改排班”。

## 回归结果

| 检查 | 最终结果 |
| --- | --- |
| 全部后端 pytest | 243 passed，14 skipped |
| 新增后端回归 | 44 项，包含 14 个离线评测契约 |
| frontend lint | 通过 |
| frontend build | 通过 |
| Playwright Chromium | 20 passed，其中新增 1 个连续问答只读回归 |
| git diff --check | 通过 |

静态模式的 14 skipped 是显式关闭的 Live Evaluation，不算真实模型通过。已有 Generate/Replan/Validate/Confirm、Scenario、Force Generate、版本保护、持久化、SSE 和幂等测试均保留。Playwright 还检查了新增分析时间线、当前排班未改变及刷新恢复。

开发中修复了新旧只读分支重复执行、周次误识别为建议序号、请假影响建议兼容性和历史读取强行申请写锁等问题。最后一处改为只有 bootstrap 才申请写锁，纯读取支持 SQLite query_only。

## 真实 LLM Evaluation

真实调用项目 `.env` 配置的 `gpt-5.6-sol`。评测入口仅加载 LLM 设置，不加载 `.env` 的 DATABASE_URL 或 APP_ENV。每例单独构造 SQLite 数据库、固定 16 个员工、两版排班和建议历史。fixture 完成后启用 SQL 写保护及 SQLite query_only，前后比较全部表。dry-run 不持久化会话；生产会话/SSE/幂等另由集成测试验证。

支持 LIVE_AGENT_EVAL、LLM_EVAL_MODEL、LLM_EVAL_CASE_FILE、LLM_EVAL_TIMEOUT_SECONDS、LLM_EVAL_OUTPUT_DIR。无开关或无凭据时显式 skipped。JSON 报告保存模型、耗时、提示词版本、可见原始输出、规范化计划、工具顺序/参数/输出、最终答案、时间线和失败分类；不保存 API Key 或隐藏推理。

检查使用 schema、预期字段、工具白名单、固定快照员工名单/人数、Validator 一致性、完整事实句比较和数据库快照，没有使用 LLM Judge。

| 运行 | 结果 |
| --- | --- |
| v1，14 例完整运行 | 12 passed，2 timeout |
| v2，14 例完整运行 | 11 passed，3 provider_error（connection_error） |
| v2 定向复测及最后单例复测 | 3 个失败问题最终均通过；其中饮品问题第一次复测出现 timeout |
| v2 每例最新结果汇总 | **14/14 passed，所有数据库快照不变** |
| v2 每例最新原始模型计划 | **13/14 符合预期**；“周日早班少一个人行不行”原始类型为 coverage_analysis，后端纠正为 staffing_explanation |

14/14 是定向复测后的逐例结果，不是一次完整运行全绿。v2 共 18 个 case 执行记录，其中 4 次外部请求失败，原始报告均保留。

失败样例：v1 的 E01 周一缺席、E15 周日早班为 timeout；v2 的周日上班名单、周日晚班饮品技能、不引用历史建议为 provider_error；饮品问题第一次定向复测为 timeout。原始模型分类偏差记为 wrong_intent，与最终后端结果分开记录。最终没有未修复的事实不一致、隐式历史引用或数据库写入失败。

报告位于 `artifacts/agent-evals/phase1-final-summary.json`，其中记录每例的原始报告路径、所有 v2 执行记录及失败历史。使用说明与样例见 `tests/evals/README.md`、`tests/evals/agent_cases.json`。

复现：

```powershell
$env:LLM_EVAL_TIMEOUT_SECONDS = '180'
$env:LLM_EVAL_OUTPUT_DIR = 'artifacts/agent-evals/new-run'
.venv/Scripts/python.exe -m tests.evals -p no:cacheprovider
```

## 剩余风险与边界

- Provider 响应稳定性仍是风险：本次真实调用出现连接中断和超时；业务层有确定性降级，但实时评测仍将 Provider 失败判为失败。
- 多天混合分析会要求澄清；没有明确日期的移除问题也要求补充对象，不猜测员工或班次。
- 反事实目前穷举直接移除和单人替代，不提供全局唯一性证明；目标值比较明确未知。
- 回答采用完整事实句组织，风格自由度较低，但防止了数字正确却归属错误的自然语言幻觉。
- build 有超过 500 kB 的 chunk 提示；pytest 有现有依赖弃用及 scenario 枚举序列化提示，均不影响通过。
- Solver excess staffing objective 留在第二阶段。
