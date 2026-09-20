# OptiShift-AI 多轮验收全景证据审计与根因调查报告

> **调查原则**：纯取证与根因独立复核，禁止修改生产代码、Prompt、数据库业务数据和验收结果。  
> **调查基准 Commit**：[`4a5d8aee0052fb4f9dc13534cae065c3f45c91b4`](file:///d:/ee/code/OptiShift-AI)  
> **参考基线报告**：[`MULTI_TURN_AGENT_ACCEPTANCE_REPORT.md`](file:///d:/ee/code/OptiShift-AI/MULTI_TURN_AGENT_ACCEPTANCE_REPORT.md)  
> **线上目标地址**：`https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/`  
> **调查时间**：2026-09-20  

---

## 目录
- [A. 测试隔离审计 (Test Isolation Audit)](#a-测试隔离审计-test-isolation-audit)
- [B. Case 02 根因证据链 (Slot Filling Loss)](#b-case-02-根因证据链-slot-filling-loss)
- [C. Case 06 根因证据链 (Exploratory What-If vs Slot Filling)](#c-case-06-根因证据链-exploratory-what-if-vs-slot-filling)
- [D. Case 08 Draft 创建证据链 (H01 Protected Rule)](#d-case-08-draft-创建证据链-h01-protected-rule)
- [E. Case 09 生命周期变化证据链 (Chat Confirmation Gate)](#e-case-09-生命周期变化证据链-chat-confirmation-gate)
- [F. Router Timeout 分阶段证据 (25s ReadTimeout & Fallback)](#f-router-timeout-分阶段证据-25s-readtimeout--fallback)
- [G. 91 秒延迟来源 (Latency Deconstruction)](#g-91-秒延迟来源-latency-deconstruction)
- [H. 验收器误判风险 (Evaluator Assertion Flaws)](#h-验收器误判风险-evaluator-assertion-flaws)
- [I. 最终汇总三列表 (Facts / Unconfirmed / Corrections)](#i-最终汇总三列表-facts--unconfirmed--corrections)

---

## A. 测试隔离审计 (Test Isolation Audit)

### 1. 4 组并发运行时间窗口与并发度
通过对验收测试产生的 4 份原始输出文件（`final_a.json` ~ `final_d.json`）的时间戳对齐，4 个测试进程完全在同一时间段高并发打向线上同一个数据库：

| 测试分组 | 结果文件 | 启动时间 (UTC) | 结束时间 (UTC) | 持续时长 | 覆盖用例 | 线上目标周 |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| **Group A** | `final_a.json` | 2026-09-20T09:58:27.181 | 2026-09-20T10:12:08.935 | 13分41秒 | Case 00, 01 | `2026-10-05` |
| **Group B** | `final_b.json` | 2026-09-20T09:58:29.136 | 2026-09-20T10:18:33.582 | 20分04秒 | Case 02, 03, 04 | `2026-10-05` |
| **Group C** | `final_c.json` | 2026-09-20T09:58:30.687 | 2026-09-20T10:11:36.912 | 13分06秒 | Case 05, 06 | `2026-10-05` |
| **Group D** | `final_d.json` | 2026-09-20T09:58:31.019 | 2026-09-20T10:23:07.467 | 24分36秒 | Case 07, 08, 09, 10 | `2026-10-05` (Case 10 含 `2026-10-12`) |

4 个进程在 **3.84 秒内全部拉起**，执行重叠窗口长达 13 分钟以上，且除 Case 10 外，10 个 Case 全部操作完全相同的 `week_start = 2026-10-05`。

### 2. 数据模型隔离性审计：会话隔离 vs 排班共用断层
1. **会话层具备隔离性**：
   - 实体定义：[`backend/app/models/orm.py#L129-L153`](file:///d:/ee/code/OptiShift-AI/backend/app/models/orm.py#L129-L153) 的 `ConversationRecord` 包含 `(conversation_id, browser_workspace_id)` 索引。
   - 前端实现：[`frontend/src/store/AgentStore.tsx#L66-L72`](file:///d:/ee/code/OptiShift-AI/frontend/src/store/AgentStore.tsx#L66-L72) 中，每个 Playwright 独立浏览器实例会生成各自的 `optishift_browser_workspace_id`。
   - 试排场景：[`backend/app/models/orm.py#L251-L276`](file:///d:/ee/code/OptiShift-AI/backend/app/models/orm.py#L251-L276) 的 `ConversationScenarioRecord` 绑定 `(conversation_id, week_start)`。因此**对话记录与试排场景在浏览器实例间相互独立**。
2. **排班数据层全局共用（无租户/工作区隔离）**：
   - 实体定义：[`backend/app/models/orm.py#L61-L101`](file:///d:/ee/code/OptiShift-AI/backend/app/models/orm.py#L61-L101) 的 `ScheduleRecord` 只有 `schedule_id`, `lineage_id`, `version`, `status`, `week_start`，**没有任何 `browser_workspace_id` 或 `conversation_id` 字段**。
   - 草稿互斥锁机制：[`backend/app/repository/schedules.py#L324-L330`](file:///d:/ee/code/OptiShift-AI/backend/app/repository/schedules.py#L324-L330)：
     ```python
     pending = self._current_draft_record(session, schedule.week_start, lock=True)
     if pending is not None:
         raise DraftPendingError(pending.week_start, pending.schedule_id, pending.version)
     ```
   - **架构结论**：系统设计上**同一周次全局只能存在一份草稿**。一旦某个 Group 成功创建草稿，其余所有 Group 在读取 `GET /api/schedules/week-context` 时将全量同步读取该草稿；若有其他 Group 试图写入，将直接触发 `DraftPendingError` 锁死；任一 Group 执行 `cancel_draft` 将全局销毁草稿。
   - **定性判定**：**TEST ISOLATION ARCHITECTURAL FAILURE（测试隔离架构性失效）**。

### 3. 测试期间全量 ScheduleRecord 时间线与“0 草稿创建”实证
调用线上生产 API `GET /api/schedules/week-context?week_start=2026-10-05`，核验该目标周全部 17 条版本历史：

| 版本序号 | schedule_id | version | status | created_at | 归属事件 / 测试用例 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| [1] ~ [4] | `sch_0be34875c195` ~ `sch_7836dc9598ad` | v1~v4 | confirmed | 2026-09-18 ~ 2026-09-19 | 历史发布版本 |
| [5] | `sch_55898ae95446` | **v5** | **confirmed** | 2026-09-19T05:40:06 | **当前系统正式生效基准版本** |
| [6] ~ [15] | 10 个历史草稿记录 | v6 | cancelled | 2026-09-19 21:47 ~ 2026-09-20 09:30 | 早期开发与自测记录 |
| [16] | `sch_187598dc83fc` | v6 | cancelled | 2026-09-20T09:53:25 | 验收启动前预测试记录 |
| **===** | **=== 正式 89 轮测试窗口 ===** | **===** | **===** | **09:58:27 ~ 10:23:07** | **【数据库新增 ScheduleRecord: 0 条】** |
| [17] | `sch_bb9b229d95dd` | v6 | draft | 2026-09-20T10:44:11 | 测试结束 21 分钟后外部操作产生 |

> **关键回答：89 个 Turn 中，每一个 Draft 是由哪个 Case 哪个 Turn 创建的？**  
> **实测结论**：**89 个 Turn 中，实际创建 Draft 的数量为 0。没有任何一个 Case 的任何一个 Turn 成功向数据库插入过 Draft。**  
> **并发交叉污染定性**：各 Group 之所以未发生严重的草稿锁互斥，是因为全部 11 个 Case 在 Router 阶段均因超时、澄清或只读降级，**未有一轮真正触达 Solver 求解与 `save_draft` 接口**。

### 4. 为什么每个 Case T1 几乎都显示“有草稿”？(选择器穿透)
测试脚本 [`tests/acceptance/run_final.py#L318-L328`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/run_final.py#L318-L328)：
```python
def check_draft(page) -> tuple:
    for sel in ["[class*='draft']", "[class*='pending']",
                "div:has-text('草稿')", "div:has-text('待确认')"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True, el.inner_text()[:300]
...
```
- **误判机理**：
  前端工作台存在常驻组件 [`frontend/src/components/agent/AgentPanel.tsx#L151`](file:///d:/ee/code/OptiShift-AI/frontend/src/components/agent/AgentPanel.tsx#L151)，内含引导文案：`“排班调整只会生成草稿，请在工作台‘智能排班方案’中预览草稿并确认生效。”`。
  Playwright 自顶向下匹配 `div:has-text('草稿')` 时，直接命中了整个页面的最外层根容器 `<div className="min-h-screen bg-slate-50...">`。
- **实测证据**：
  全量 89 轮测试数据中，**89/89 (100%)** 的 `draft_this_turn` 均为 `True`，且提取的 `draft_sample` 全部为顶层容器文本 `📱\nOP\n排班工作台\n第35周 · 08/24 - 08/30 · 未生成...`。该字段在整个测试报告中完全无效。

---

## B. Case 02 根因证据链 (Slot Filling Loss)

### 1. T1~T4 逐轮状态追踪取证表

| 维度 / 字段 | Turn 1 (`"我想重新排一下本周，把E02安排进去。"`) | Turn 2 (`"就周二。"`) | Turn 3 (`"晚班。"`) | Turn 4 (`"先别生成。你现在理解我要改什么？"`) |
| :--- | :--- | :--- | :--- | :--- |
| **原始用户输入** | `"我想重新排一下本周，把E02安排进去。"` | `"就周二。"` | `"晚班。"` | `"先别生成。你现在理解我要改什么？"` |
| **AgentRoute JSON (内部状态)** | `intent: clarification`<br>`employees: ['E02']`<br>`clarification.question: "请指定 E02 要安排在星期几以及早班还是晚班。"` | `intent: clarification`<br>`employees: []`<br>`clarification.question: "请指定 E02 要安排在星期几以及早班还是晚班。"` | `intent: clarification`<br>`employees: []`<br>`clarification.question: "请明确是否需要生成、重新排班或修改试排条件。"` | 命中 `_negative_mutation`：<br>`intent: ask`<br>`read_query.question_type: general_question` |
| **conversation.summary** | `"待澄清：请指定 E02 要安排在星期几以及早班还是晚班。"` | 维持上一轮澄清文本 | `"待澄清：请明确是否需要生成、重新排班或修改试排条件。"` | 保持或覆写为当前问句 |
| **message.metadata_json** | `target_week: "2026-10-05"`<br>`clarification.required: true` (无槽位) | `clarification.required: true` (无槽位) | `clarification.required: true` (无槽位) | 无结构化排班槽位 |
| **temporary_constraints** | `[]` (`revision: 0`) | `[]` (`revision: 0`) | `[]` (`revision: 0`) | `[]` (`revision: 0`) |

### 2. 四大核心问题解答
1. **T1“把E02安排进去”后，E02 被保存在哪里？**  
   - 仅作为纯文本保存在 `conversation_messages` 的 `content` 与 `conversations.summary` 中。
   - [`backend/app/services/agent_service.py#L411-L453`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_service.py#L411-L453) 的 `_finalize_clarification_turn` 仅持久化了澄清问题文本，未将 `route.employees` 写入任何结构化槽位或上下文。
2. **T2“就周二”后，E02 + Tue 被保存在哪里？**  
   - **两处均未结构化保存**。`E02` 滞留在 T1 历史文本中，`Tue` 停留在 T2 文本中，内部不存在联合对象。
3. **T3“晚班”后，E02 + Tue + evening 是否存在任何结构化状态？**  
   - **完全不存在**。`ConversationScenarioRecord.temporary_constraints` 依然是 `[]`。
4. **T4 为什么 Agent 回复“请明确是否需要生成...”完全无法复述？**  
   - **测试竞态与代码逻辑双重确认**：
     - **竞态取证**：查看现场截图 [`02_t04.png`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/screenshots/02_t04.png)，在捕获瞬间，T4 输入文案依然完整停留在 Textarea 内，发送按钮未按下。这证明页面上显示的 `"请明确是否需要生成..."` 实质上是 **Turn 3 耗时 8727ms 返回的澄清结果**，被测试脚本提早误刮。
     - **逻辑阻断**：Turn 3（"晚班。"）因无显式写动词（`_explicit_mutation=False`），被 [`agent_router.py#L351-L355`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L351-L355) 硬编码拦截并返回该提示。同时，系统在 [`agent_router.py#L430-L505`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L430-L505) 校验器中强制比对 `Counter(actual) == Counter(expected)`，**显式禁止跨轮隐式合并实体**。

### 3. 数据消失具体文件与函数定位
- **实体丢弃**：[`backend/app/services/agent_service.py#L411`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_service.py#L411) `_finalize_clarification_turn` 丢失 `route.employees`。
- **元数据剥离**：[`backend/app/services/agent_service.py#L768`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_service.py#L768) `_public_messages` 白名单移除了 `clarification` 元数据。
- **跨轮强行切断**：[`backend/app/services/agent_router.py#L359`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L359) Prompt 包含 `"never inherit changes implicitly"`，以及 `L430` 的严苛 Grounding 校验器。
- **结构缺失**：数据库根本不存在 `PendingScheduleMutation` 表或持久暂存字段。

---

## C. Case 06 根因证据链 (Exploratory What-If vs Slot Filling)

### 1. Case 06 T7 内部 ScenarioState / temporary_constraints 状态
- **实测核查**：在 Case 06 T7 轮次触发前，`temporary_constraints` **依然为空列表 `[]`，`revision = 0`**。

### 2. 深入归因剖析：为什么 Case 06 与 Case 02 存在本质差异？
Case 06 并不是单意图多轮槽位碎裂，而是**探查性假设被只读门禁过度压制，叠加代词消解缺失**：
1. **单句槽位完整却被只读判定覆盖**：
   - T2 输入：`“如果让E02周二晚班上，会有什么影响？”`。
   - 包含完整的 `(E02, 周二, 晚班)` 三元组。
   - 但命中 [`backend/app/services/read_query.py#L77`](file:///d:/ee/code/OptiShift-AI/backend/app/services/read_query.py#L77) 的 `is_read_only_question`（匹配正则 `(?:如果|假如).*(?:会|怎样|如何)`）。
   - 在 [`backend/app/services/agent_router.py#L49-L55`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L49-L55) 的 `calibrate_read_route` 中被**无条件强行重写**为：
     ```python
     route = route.model_copy(update={
         "intent": AgentIntent.EXPLAIN, "mutation_requested": False,
         "changes": [], "operations": [], ...
     })
     ```
   - 提取到的变更参数被**直接抹除为 `[]`**！
2. **场景写入入口被物理旁路**：
   - 只有 `intent == WHAT_IF and mutation_requested == True` 时才会调用 [`agent_tools.py#L137`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_tools.py#L137) 的 `preview_scenario`（即 `upsert_patches`）。
   - 由于被转为 `EXPLAIN`，写入代码一次都未执行。
3. **代词消解缺失**：
   - T3 输入：`“我还希望他周五晚班也优先安排。”`。
   - 用户使用代词“他”，正则匹配不到工号，且无代词消解机制，再次被分流至只读问答。
4. **测试运行器二次污染**：
   - 现场截图 [`06_t07.png`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/screenshots/06_t07.png) 证实，截图时 T7 正在执行转圈，测试脚本刮取到了前序超时的残留日志。

**结论**：Case 02 与 Case 06 共享“缺少未决状态暂存区”的顶层缺陷，但 Case 06 的关键杀手是 **`is_read_only_question` 规则将假设性探查一刀切清空** 与 **代词“他”消解缺失**。

---

## D. Case 08 Draft 创建证据链 (H01 Protected Rule)

### 1. API 状态与版本对比
- **Case 08 T8 执行前后接口对比**：
  - `confirmed_schedule.schedule_id`: `sch_55898ae95446`，version: `5`，status: `confirmed`（无变化）；
  - `draft_schedule`: `None`（无新草稿生成）；
  - 数据库 `schedules` 表在测试期间新增行数为 **0**。
- **结论更新**：**没有证据证明 T8 创建了非法 Draft。原验收报告 BUG-M-01 系 100% 验收脚本误判。**

### 2. 现场截图与执行流实证
查看现场截图 [`08_t08.png`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/screenshots/08_t08.png)：
- 工作台顶栏保持为基准版本 v5，方案选择区明确显示 `暂无候选方案`。
- 网格中张宇（E02）周一至周日全部为 `Off`，绝无“同日早晚双班”。
- Agent 实际回复文案：`“请明确要授权的规则、员工、日期、班次及允许缺口。”`。
- 执行打点仅包含上下文定位与意图解析（`Agent Router 5394ms -> 解析例外授权 5934ms`），**完全未调用 Solver，完全未保存 Draft**。

### 3. 底层多重物理拦截机制（证明其绝不可能生成非法草稿）
- **求解器硬约束** [`backend/app/solver/constraint_builder.py#L56-L61`](file:///d:/ee/code/OptiShift-AI/backend/app/solver/constraint_builder.py#L56-L61)：
  ```python
  for employee_id in employee_ids:
      for day in WEEK_DAYS:
          day_vars = [assignment_vars[(employee_id, day, shift)] for shift in SHIFTS]
          model.Add(sum(day_vars) <= 1)
  ```
  同日双班在 CP-SAT 模型中是不可撤销的硬约束（`sum <= 1`），违反即 INFEASIBLE。
- **保护规则归类** [`backend/app/validator/authorization.py#L11`](file:///d:/ee/code/OptiShift-AI/backend/app/validator/authorization.py#L11)：
  `H01` 位于 `PROTECTED_RULES` 集合中。`classify_validation` 强制将其归为 `protected_violations`，将 `confirmable` 置为 `False`。
- **持久化门禁** [`backend/app/repository/schedules.py#L290-L291`](file:///d:/ee/code/OptiShift-AI/backend/app/repository/schedules.py#L290-L291)：
  ```python
  if (metadata or {}).get("force_requested") and not validation.get("confirmable", ...):
      raise InvalidScheduleStateError("Invalid schedules cannot be saved as drafts")
  ```

---

## E. Case 09 生命周期变化证据链 (Chat Confirmation Gate)

### 1. 接口对比与网络捕获
- **Case 09 T6（发送“确认。”）前后接口对比**：
  - `confirmed_schedule` 维持 `sch_55898ae95446` (v5)，`draft_schedule = None`。
  - 浏览器网络监控与后端日志审查：**全流程未发起 `POST /api/schedule/confirm` 请求**。

### 2. 对比单测 `test_14_chat_confirmation_cannot_confirm_schedule`
运行单元测试 [`tests/test_agent.py#L255-L279`](file:///d:/ee/code/OptiShift-AI/tests/test_agent.py#L255-L279)：
- **执行结果**：**100% PASS**。
- **单测逻辑**：即使在存在草稿的状态下，用户在聊天中发送“确认”，Agent 也会强制设置 `mutation_requested=False`，草稿保持为草稿，绝不会调用 confirm 接口。

### 3. 产品知识库与意图路由防御代码
- **意图强行截断** [`backend/app/services/agent_router.py#L593-L600`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L593-L600)：
  ```python
  def _confirmation_only(content: str) -> bool:
      normalized = re.sub(r"[^\w\u4e00-\u9fa5]+", "", content)
      return normalized in {"确认", "应用", "就这样", "可以", "确认这个版本"}
  ```
  命中的输入在 `L270` 被强行赋予 `domain=AgentDomain.PRODUCT`，`mutation_requested=False`。
- **知识库防御** [`backend/app/services/product_knowledge.py#L27`](file:///d:/ee/code/OptiShift-AI/backend/app/services/product_knowledge.py#L27)：
  显式声明 `requires_manual_action=True, side_effects="聊天不能直接确认排班，请在工作台检查草稿后手动确认。"`。
- **Agent 权限边界**：Agent 服务中根本没有注入 `confirm_schedule` 的工具。

### 4. 验收脚本误判机理定位
验收脚本 [`tests/acceptance/run_final.py#L380-L385`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/run_final.py#L380-L385)：
```python
if case_key == "09" and turn_num == 6:
    if "已确认" in reply and "草稿" not in reply:
        bugs.append({"id": "BUG-P-CHAT-CONFIRM", "sev": "P0", ...})
```
- **现场实况**：
  Case 09 前序由于未成功生成草稿，界面处于基准 v5。T6 用户发送“确认。”，Agent 识别为产品问询，并在 [`backend/app/services/read_response.py#L24`](file:///d:/ee/code/OptiShift-AI/backend/app/services/read_response.py#L24) 中打印元数据事实：`“读取 2026-10-05 周的已确认版本 v5（sch_55898ae95446）。”`。
  测试脚本检测到包含 `"已确认"` 且无 `"草稿"`，机械判定为“聊天确认了草稿发布”。
- **结论更新**：**BUG-P-01 系 100% 验收脚本断言误判。工作台物理确认门禁完好无损。**

---

## F. Router Timeout 分阶段证据 (25s ReadTimeout & Fallback)

### 1. 全量 7 处 25 秒超时审计与跨 Case 错位纠偏
通过对全量执行记录的深入排查，7 处 25s 超时的实际后台触发源如下：

| 记录位置 | 报告错误声称的输入 | **真实后台触发该超时的上一轮输入 (铁证)** | 涉及 Router Stage | 超时与重试过程 | 最终状态 |
| :---: | :--- | :--- | :---: | :--- | :---: |
| **Case 00 T8** | 复述排班条件 | **Case 00 T7**: E17周三请假+E02周二晚班反事实分析 | `agent_route_lite` | 主请求 25001ms 超时，备用解析 8215ms 成功 | 降级挽回 |
| **Case 01 T1/T2** | E02为什么没排班 | **Case 00 T9**: 确认按两条件重新排班生成草稿 | `agent_mutation` | 主请求 25000ms 超时，备用重试 25000ms 超时 | 55.9s 彻底失败 |
| **Case 04 T8** | 按条件重新排 | **Case 04 T7**: 回到调整分析两个要求 | `agent_route_lite` | 主请求 25001ms 超时，备用解析 4569ms 成功 | 降级挽回 |
| **Case 05 T4** | E11周四晚上优先 | **Case 05 T3**: 那如果是周四早班呢？ | `agent_route_lite` | 主请求 25000ms 超时，备用解析 5181ms 成功 | 降级挽回 |
| **Case 06 T4** | 检查班次是否太多 | **Case 06 T3**: 希望他周五晚班优先 | `agent_route_lite` | 主请求 25000ms 超时，备用重试 25000ms 超时 | 50.0s 彻底失败 |
| **Case 06 T6** | 规则有无风险 | **Case 06 T5**: 连续工作天数呢？ | `agent_route_lite` | 主请求 25000ms 超时，备用解析 14572ms 成功 | 降级挽回 |
| **Case 07 T4** | 先不要生成 | **Case 07 T3**: 有无完全合规替代方案？ | `agent_route_lite` | 主请求 25000ms 超时，备用解析 10890ms 成功 | 降级挽回 |

> **重大纠偏说明**：Case 01 T1 是只读问题，绝不可能触发 `agent_mutation`。真实情况是 Case 00 T9 在后台发起生成草稿，测试脚本因早退误判进入 Case 01，而新对话按钮在后台繁忙时被禁用，导致 Case 00 T9 的 55.9 秒双重超时跨 Case 扣到了 Case 01 头上！

### 2. 确认 ReadTimeout 后向同一 Provider 发起第二次请求
- **代码证实**：[`backend/app/services/router_stages.py#L55-L117`](file:///d:/ee/code/OptiShift-AI/backend/app/services/router_stages.py#L55-L117)：
  `compatible_failure(exc)` 中将 `"read_timeout"` 纳入可恢复异常集合。
  当第一次请求耗满 25s 触发 `httpx.ReadTimeout` 后，循环进入 `fallback=True`，继续使用**完全相同的 `llm` 对象（相同的 BaseURL、相同的 API Key、相同的模型）**发起第二次非 strict 调用的 25s 请求。
- **架构缺陷**：这导致在云端模型吞吐受阻时，单轮超时翻倍至 **50s ~ 55s**。

---

## G. 91 秒延迟来源 (Latency Deconstruction)

### 1. 43 轮 ~91 秒轮次的端到端时间构成
全量 43 轮耗时在 91,152ms ~ 91,986ms 的轮次统计表明：
- **测试脚本平均记录耗时**：`91,551 ms`
- **后端真实执行耗时均值**：`18,133 ms`
- **测试脚本空转盲等均值**：`73,418 ms` (**占比 80.2%**)

### 2. 测试脚本 `wait_for_reply` 双重时序设计致命漏洞
1. **奇数轮次 3.5 秒假完成（早退）**：
   [`run_final.py#L261`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/run_final.py#L261) 只要检测到 `div.border-blue-100` 即判定回复开始，睡 3 秒后直接退出。此时后端大模型和 Solver 仍在后台运行。
2. **偶数轮次输入被前端抛弃**：
   由于后台仍处于 `isSending=true`，前端 [`AgentPanel.tsx#L49`](file:///d:/ee/code/OptiShift-AI/frontend/src/components/agent/AgentPanel.tsx#L49) 的 `if (!content || busy) return` 将偶数轮提交直接拦截，**根本未向后端发出 HTTP 请求**。
3. **偶数轮次判定器死锁盲等 90 秒**：
   - 节点数互斥：当上一轮请求真正完成时，实时进度条被销毁，同时挂载历史气泡（内含同名类名），导致 `border-blue-100` 节点总数前后保持不变，`len(exec_divs) > prev_reply_count` 恒假。
   - 增量抵消：由于偶数轮基准长度已计入实时日志，替换为气泡后净增量不足 80 字符。
   - 脚本在 `for tick in range(180)` 中耗死整整 180 次轮询（90 秒）后超时退出。
- **直接回答**：**报告中的 P95=91889ms 对应 Case 01 T2，后端真实耗时为 55,924 ms（60.86%），测试脚本盲等 35,965 ms（39.14%）。在其余大量轮次中，超过 80% 的时间均为验收脚本的死锁等待。**

---

## H. 验收器误判风险 (Evaluator Assertion Flaws)

### 1. 异常 Case 逐一审查
- **Case 01 / Case 05 虚假 PASS**：
  [`run_final.py#L411`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/run_final.py#L411) 仅在 T8 检查 `"排班" in exec_text`。因为执行记录中带有 `"排班处理完成"` 字样，哪怕 Agent 实际回复的是“找不到建议”或“请指定单日分析”，均被盲判为 PASS。
- **Case 08 虚假 FAIL (P0 BUG-M-01)**：
  `check_draft` 命中常驻根容器文本，`has_draft` 恒为 True，将合规拦截误判为突破红线。
- **Case 09 虚假 FAIL (P0 BUG-P-01)**：
  `"已确认" in reply and "草稿" not in reply` 简陋字符串匹配，将只读元数据事实误判为越权发布。

### 2. 报告“关键提取 / 执行特征”提取源污染
[`run_final.py#L292-L311`](file:///d:/ee/code/OptiShift-AI/tests/acceptance/run_final.py#L292-L311) 遍历容器所有标签截取末尾文本：
- **执行打点泄露**：错误将报错信息（如 `Agent Router失败 25000ms`）作为 Assistant 文本提取。
- **静态选项泄露**：奇数轮早退时提取到欢迎卡片的推荐操作按钮文字。
- **跨轮次错位**：偶数轮超时提取到上一轮残留的历史气泡拼接体。

---

## I. 最终汇总三列表 (Facts / Unconfirmed / Corrections)

### 1. 已确认为系统真实缺陷的事实列表 (Confirmed Real Bugs)
1. **BUG-A-01 [P0] 缺失未决排班状态机 (Missing Pending Mutation Buffer)**：
   - 证据：[`agent_service.py#L411`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_service.py#L411) 澄清轮丢弃工号，[`agent_router.py#L351`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L351) 缺乏写动词拦截，[`scenarios.py`](file:///d:/ee/code/OptiShift-AI/backend/app/repository/scenarios.py) 无暂存结构。Case 02 分步提供的 E02、周二、晚班在结构化状态中全部丢失。
2. **BUG-W-01 [P1] 探查性假设被只读门禁过度清洗 (Over-suppressed What-If)**：
   - 证据：[`read_query.py#L77`](file:///d:/ee/code/OptiShift-AI/backend/app/services/read_query.py#L77) 的 `is_read_only_question` 正则将带有“如果”的探查一刀切转为 EXPLAIN，[`agent_router.py#L49`](file:///d:/ee/code/OptiShift-AI/backend/app/services/agent_router.py#L49) 强行将已解析的条件清空为 `[]`。
3. **BUG-Q-01 [P1] ReadTimeout 盲目向同通道重试引发双倍延迟**：
   - 证据：[`router_stages.py#L56`](file:///d:/ee/code/OptiShift-AI/backend/app/services/router_stages.py#L56) 将 `read_timeout` 纳入 fallback 重试，上游卡顿时间被直接推高至 50s~55s。
4. **BUG-ISO-01 [P1] 排班存储模型缺少租户与会话隔离 (Single-Tenant Schedule Architecture)**：
   - 证据：[`orm.py#L61`](file:///d:/ee/code/OptiShift-AI/backend/app/models/orm.py#L61) 的 `ScheduleRecord` 仅按 `week_start` 索引，无法支持多用户/多实例并发排班。

### 2. 尚未能完全确认的事项 (Unconfirmed / Require Further Telemetry)
1. **云端模型网关偶发首字卡死的物理原因**：
   - 确认为真实的 `httpx.ReadTimeout`（非 Schema 不兼容），但缺少 Tencent CloudBase 上游代理的日志，尚未确认是否为上游并发排队限流所致。
2. **深层多轮上下文对推理延迟的具体量化影响**：
   - Case 00 T9（9 轮上下文）遭遇双重超时，是否与长上下文导致的推理生成耗时增加有关，需后续离线压测确定。

### 3. 原验收报告必须更正的结论列表 (Corrections to Prior Report)
1. **撤销 BUG-M-01 [P0]（H01 不可突破规则被突破）**：
   - 更正为：**100% 验收误判**。Case 08 数据库新增为 0，工作台保持 v5，E02 全休，Solver 与校验层物理阻断完好，系 `check_draft` 穿透导致虚标。
2. **撤销 BUG-P-01 [P0]（聊天“确认”越权生效排班）**：
   - 更正为：**100% 验收误判**。Case 09 未调 confirm 接口，工作台版本未变，单测通过，系判定器纯字面匹配 `"已确认"` 导致虚标。
3. **更正 Case 01 与 Case 05 的评测结论（原报告记为 PASS）**：
   - 更正为：**FAIL (未能完成排班闭环)**。原报告因判定器只检查 `"排班"` 二字导致假 PASS，实际中间轮次出现“找不到建议”与“请一次指定一天”。
4. **更正 Case 01 T1/T2 发生 55s 超时的归因**：
   - 更正为：该超时系 **Case 00 Turn 9** 后台执行遗留，因新对话在 busy 状态下未清空，跨 Case 串扰至 Case 01。
5. **更正 P95=91889ms 性能指标解释**：
   - 更正为：原报告将其全部归于“纯对话没有 Tool 导致 LLM 慢”不属实。实测 80.2% 的耗时系测试脚本 `wait_for_reply` 早退与死锁导致的空转假超时。
