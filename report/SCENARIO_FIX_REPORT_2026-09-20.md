# OptiShift-AI 修复、发布与线上验收报告

日期：2026-09-20（Asia/Hong_Kong）。测试周：2026-10-05 至 2026-10-11，2026-W41。

本轮代码已提交、推送 main，由现有 GitHub Actions 发布腾讯云，并在发布后的生产环境完成真实 Chromium 浏览器验收。A–H、M02 三次独立重复、X1、X2、C01 共 13 组检查全部通过。正式排班 v5 的 schedule_id、version、assignments SHA256 测试前后完全一致。

真实 LLM 测试没有跳过：原有 25 项全部执行，另新增 4 项，共 **29/29 PASS**。全量 pytest 为 **393 passed，0 skipped**。CI 本身配置 `LLM_ENABLED=false`，其结果不替代上述真实 Provider 证据。

- 业务修复 Commit：`8eac04f1b44ec9e3ad102c64c3af40699af86e61`，提交信息 `fix agent scheduling scenario flow`。
- 最终 main：`4a5d8aee0052fb4f9dc13534cae065c3f45c91b4`，提交信息 `test: scope production chat checks and wait for hydration`，仅修正验收脚本选择器及网络等待。
- CI/CD：[GitHub Actions #35501690261](https://github.com/jiacan233/OptiShift-AI/actions/runs/35501690261)。
- 腾讯云：[生产链接](https://optishift-ai-299444-11-1471387898.sh.run.tcloudbase.com/)。
- 发布前在线版本：`optishift-ai-042`；发布后：`optishift-ai-044`。
- 完整生产验收记录：[production-browser-final/results.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/results.json)。

## 已有修复复核

1. AAA 数据污染：发布前及生产验收均读取员工主数据，只有 E01–E20，未发现 AAA，没有再次创建或盲删员工。
2. 默认域名：API 正常；全新浏览器可能收到 CloudBase 的 404 访问提示页，点击“确定访问”后正常进入应用。已按用户补充意见继续使用该测试域名，未绑定自定义域名、未重复修改域名配置。它属于平台提示页，不能声称已消除。证据：[domain-check.png](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/domain-check.png)、[domain-docs.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/domain-docs.json)。

## 根因与修复

|问题|已确认根因|修复|
|---|---|---|
|M02 preference 丢失 shift|ScenarioPatch 不存 shift；多个 Patch→Change 转换重新手写对象；旧分组键未含 shift；REPLAN fallback 漏 operations|ScenarioPatch 增加并验证 shift；统一双向转换、canonical operations 和 preview 输入入口；operations 优先并检查 legacy changes 一致性；分组包含 shift，保留顺序|
|Repair suggestion 误删其他条件|候选验证按 day 从所有 patch 删除日期，与实际应用语义不同|候选验证和实际应用共享 reducer；ADD/REMOVE 精确匹配 employee/type/shift/day；记录 candidate_changes，浏览器验证实际 state 完全一致|
|SET/CLEAR 回归风险|单纯扩大匹配键会让 SET 留下旧 shift 或 CLEAR 清不干净|SET 替换指定员工及条件类型，同批多日期/班次保持完整；CLEAR 支持员工全部或指定日期；独立 reducer 测试|
|内部异常泄露|Pydantic ValidationError 属于 ValueError，被通用处理以 str(exc) 返回、持久化；HTTP/SSE 映射分散|ValidationError 单独优先处理为 500 agent_internal_error，固定安全文案；HTTP/SSE 共用 mapper；日志保留 traceback，消息和工具输出只存安全业务信息；历史回放过滤旧异常|
|历史非法 Scenario 无法加载|旧 temporary_constraints 可能已写入缺 shift preference|只作废该临时 Scenario，清缓存、递增 revision、返回 scenario_expired 提示；不猜 shift，不修改 Draft/confirmed|
|Preview 无法退出/刷新复活|退出只依赖 Draft；历史 assistant 消息重建 infeasibleResult|新增 UI 隐藏和后端 clear 两条动作；clear 校验 workspace、week、revision、活动 turn，并幂等；成功后才清 UI；新对话、只读结果、历史加载不恢复旧面板|
|进度遗漏条件|进度过滤 shift，摘要只展示部分条件|进度及最终回复使用 canonical_conditions，显示所有条件与早班/晚班；新增稳定 testid|
|X1 建议点击被要求澄清|repair_1_mon 的 mon 被误当新日期，丢失 suggestion reference|日期判定排除显式 repair ID；显式建议引用使用持久化参数；清除过时 clarification/read_query|
|同员工多班次及 X2 保持不变|解析遗漏后半个班次，或将明确保持的条件错误继承为 SET|按当前文本完整解析独立 preference；只让/改成保持 SET；显式保持不变条件按 ADD 保留；新增真实 Provider 回归|
|验收误判|M01 旧断言要求 Draft；宽泛文本选择器将两个标题当重复 Draft；E01 名字被误判串台|不可行按 structured scenario_preview 判成功；SSE 用唯一 testid 和实际记录计数；串台检测使用旧请求语义而非裸员工 ID|

Solver 目标函数、硬约束、跨周规则、Validator 规则均未修改。不可行不会写入版本历史，未自动 Force Generate，未确认测试 Draft。可行 Preview 和保存 Draft 均继续经过独立 Validator。

## 修改文件（27 个）

|文件|
|---|
|[backend/app/api/agent.py](D:/ee/code/OptiShift-AI/backend/app/api/agent.py)|
|[backend/app/execution.py](D:/ee/code/OptiShift-AI/backend/app/execution.py)|
|[backend/app/main.py](D:/ee/code/OptiShift-AI/backend/app/main.py)|
|[backend/app/models/domain.py](D:/ee/code/OptiShift-AI/backend/app/models/domain.py)|
|[backend/app/models/scenario_changes.py](D:/ee/code/OptiShift-AI/backend/app/models/scenario_changes.py)|
|[backend/app/repository/scenarios.py](D:/ee/code/OptiShift-AI/backend/app/repository/scenarios.py)|
|[backend/app/services/agent_router.py](D:/ee/code/OptiShift-AI/backend/app/services/agent_router.py)|
|[backend/app/services/agent_service.py](D:/ee/code/OptiShift-AI/backend/app/services/agent_service.py)|
|[backend/app/services/agent_tools.py](D:/ee/code/OptiShift-AI/backend/app/services/agent_tools.py)|
|[backend/app/services/read_query.py](D:/ee/code/OptiShift-AI/backend/app/services/read_query.py)|
|[backend/app/services/scheduling_service.py](D:/ee/code/OptiShift-AI/backend/app/services/scheduling_service.py)|
|[frontend/e2e/scenario-lifecycle.spec.ts](D:/ee/code/OptiShift-AI/frontend/e2e/scenario-lifecycle.spec.ts)|
|[frontend/e2e/scheduling.spec.ts](D:/ee/code/OptiShift-AI/frontend/e2e/scheduling.spec.ts)|
|[frontend/e2e/stream-helper.ts](D:/ee/code/OptiShift-AI/frontend/e2e/stream-helper.ts)|
|[frontend/src/api/client.ts](D:/ee/code/OptiShift-AI/frontend/src/api/client.ts)|
|[frontend/src/components/agent/AgentPanel.tsx](D:/ee/code/OptiShift-AI/frontend/src/components/agent/AgentPanel.tsx)|
|[frontend/src/components/agent/AgentTrace.tsx](D:/ee/code/OptiShift-AI/frontend/src/components/agent/AgentTrace.tsx)|
|[frontend/src/components/agent/SuggestionCard.tsx](D:/ee/code/OptiShift-AI/frontend/src/components/agent/SuggestionCard.tsx)|
|[frontend/src/components/schedule/ConflictView.tsx](D:/ee/code/OptiShift-AI/frontend/src/components/schedule/ConflictView.tsx)|
|[frontend/src/pages/ScheduleWorkbench.tsx](D:/ee/code/OptiShift-AI/frontend/src/pages/ScheduleWorkbench.tsx)|
|[frontend/src/redesign/components/candidate/CandidatePlanCard.tsx](D:/ee/code/OptiShift-AI/frontend/src/redesign/components/candidate/CandidatePlanCard.tsx)|
|[frontend/src/store/AgentStore.tsx](D:/ee/code/OptiShift-AI/frontend/src/store/AgentStore.tsx)|
|[frontend/src/store/AppStore.tsx](D:/ee/code/OptiShift-AI/frontend/src/store/AppStore.tsx)|
|[frontend/src/types/index.ts](D:/ee/code/OptiShift-AI/frontend/src/types/index.ts)|
|[scripts/scenario_acceptance.cjs](D:/ee/code/OptiShift-AI/scripts/scenario_acceptance.cjs)|
|[tests/evals/test_live_router_eval.py](D:/ee/code/OptiShift-AI/tests/evals/test_live_router_eval.py)|
|[tests/test_scenario_flow.py](D:/ee/code/OptiShift-AI/tests/test_scenario_flow.py)|

## 测试结果

|检查|结果|证据|
|---|---|---|
|全量后端，包含真实 Provider|393 passed，0 skipped|[all-tests-live-enabled.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/all-tests-live-enabled.log)|
|最后异常分层调整后的相关后端回归|115 passed|[post-review-regression.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/post-review-regression.log)|
|真实 LLM 原有25项 + 新增4项|29 passed，0 skipped；每项真实 HTTP200，测试数据库无修改|[LIVE_LLM_AUDIT.md](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/LIVE_LLM_AUDIT.md)；[live-summary.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/live-summary.json)|
|前端 lint|PASS|[frontend-lint-final.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/frontend-lint-final.log)|
|TypeScript / build|PASS（tsc -b && vite build）|[frontend-build-final.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/frontend-build-final.log)|
|Playwright E2E|37 passed|[e2e-verified.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/e2e-verified.log)|
|本地真实浏览器/真实 LLM|全部 Case 最终通过，X1 修复后定向复测通过|[local-browser-verified/results.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/local-browser-verified/results.json)；[local-browser-repair/results.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/local-browser-repair/results.json)；[local-browser-audit/results.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/local-browser-audit/results.json)|

测试中实际发现并修复了 X1 repair ID 被识别为星期、只让 E01 路由、X2 保持不变条件遗漏、同员工两个班次偏好、E2E 流读取 race、历史 Preview 刷新断言等问题。首次生产G/H的失败同样保留为FAIL，分别是选择器范围与异步等待误判；修复脚本后重新验收，未修改业务状态架构。旧失败日志保留；报告使用修复后的复测结果。一次本地补测命令引用不存在的 test_agent_api.py，未运行用例；改用仓库实际 test_agent.py 后 115 项通过，没有跳过或删除断言。

真实 Provider 使用 `gpt-5.6-sol`，地址来自现有忽略跟踪的 `.env`。测试仅加载 LLM 配置、使用独立测试数据库，不加载生产数据库连接。逐项原始可见结构化输出、最终 route、耗时、HTTP 状态保存在 `artifacts/scenario-fix/full-live-evidence/case-*.json`，未写入 API Key 或隐藏推理。另按原 main 基线 `bde4d52` 提取原有25个用例名称，与本轮通过记录逐项比对，确认全部覆盖：[original-25-coverage.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/original-25-coverage.json)。

## 发布后的生产真实浏览器验收

运行开始：2026-09-20T09:23:47.912Z；结束：2026-09-20T09:30:30.003Z（UTC）。
浏览器为真实 Chromium，直接操作生产页面，正常点击默认域名访问提示；实际调用线上 API/LLM。没有 mock Provider。SSE H 仅在浏览器网络边界删除服务端已生成的 terminal frame，以复现断流恢复。

|Case|结果|核验内容|证据|
|---|---|---|---|
|A|PASS|三条能力问答；无 Draft，无旧 Preview，v5 不变|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/A-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/A.png)|
|B|PASS|周日→周六上下文正确；只读、无串台、正式工作台可见|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/B-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/B.png)|
|C|PASS|M01 返回不可行 Scenario；有冲突、候选建议和两个退出按钮，无 Draft|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/C-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/C.png)|
|D1|PASS|M02 第1次：三个条件完整、evening 保留、SSE 正常结束|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D1-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D1.png)|
|D2|PASS|M02 第2次：独立 browser context/conversation，同一 v5 基线|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D2-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D2.png)|
|D3|PASS|M02 第3次：独立上下文，完整进度，无500/内部异常/重复Draft|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D3-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D3.png)|
|E|PASS|原始恢复分析问句正常应答；明确变更与隔离验证另由 X1 覆盖|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/E-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/E.png)|
|X1|PASS|真实点击恢复 E01；E02 Mon leave 保留；candidate_changes 等于应用条件；预测与实际可行性一致|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/X1-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/X1.png)|
|F|PASS|M01 后同会话继续修改，重新求解，无“没有可校验的排班”|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/F-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/F.png)|
|X2|PASS|E01 Mon 保留、Tue 移除；E02 Wed evening 保留|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/X2-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/X2.png)|
|G|PASS|隐藏保留条件；结束清后端；F5、新对话不恢复旧面板|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/G-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/G.png)|
|C01|PASS|无解后只读追问无旧条件串台，旧诊断不遮挡工作台|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/C01-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/C01.png)|
|H|PASS|terminal丢失后相同client_message_id重放；唯一消息/草稿/新增版本，刷新保留Draft|[turns](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/H-turns.json) / [截图](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/H.png)|

### M02 三次独立请求记录

|Case|conversation_id|client_message_id|revision|结果/strict_feasible|schedule_id/version|
|---|---|---|---|---|---|
|D1|conv_29695f8a2f3a4328b8c5446d17bde646|cm_fdbecc6ead784097834bab174f4b772e|1|scenario_preview / false|无 Draft；正式 sch_55898ae95446 / v5|
|D2|conv_2242d6aea0ab48b2a3ddf9ee8967a57c|cm_97897abaade145219581f1e87093de84|1|scenario_preview / false|无 Draft；正式 sch_55898ae95446 / v5|
|D3|conv_295fadec83aa45ec8ae6b14dc1e82eeb|cm_f1ebb0b165b145589667d3f6a762850d|1|scenario_preview / false|无 Draft；正式 sch_55898ae95446 / v5|

### SSE 断流证据

```json
{
  "terminalDropped": true,
  "replayTriggered": true,
  "sameIdUsed": true,
  "streamId": "cm_1dae4660c27a4a4db51116b6828b64c0",
  "replayId": "cm_1dae4660c27a4a4db51116b6828b64c0",
  "assistantBubbles": 1,
  "draftCards": 1,
  "assistantRecords": 1,
  "userRecords": 1,
  "draftRecords": 1,
  "newVersionRecords": 1,
  "schedule_id": "sch_d4ebb12e79ab",
  "version": 6
}
```


assistantRecords/userRecords 来自持久化 conversation API；draftRecords/newVersionRecords 来自数据库支持的 versions API。它们都为1，且前端 bubble/card 均为1；没有用“草稿方案”文本数量替代记录计数。

## 数据保护与清理

|项目|测试前|测试后|
|---|---|---|
|confirmed schedule_id|sch_55898ae95446|sch_55898ae95446|
|confirmed version|5|5|
|assignments SHA256|815ff49548c47019d9a393e347f76225ebd835dcdd97b93c0b719f1525b45ee1|815ff49548c47019d9a393e347f76225ebd835dcdd97b93c0b719f1525b45ee1|
|active Draft|无|无|

SHA256 算法：每条 assignment 映射 `[employee_id, day, shift]`，排序后 JSON.stringify，再 SHA256。v5 实际排班内容一致，非仅检查页面版本标签。

本轮生产 Draft 在取消前均记录 schedule_id、version、client_message_id；仅对匹配本轮 conversation 的已知 Draft 调用 cancel。取消保留版本审计记录，不删除正式版本。每个本轮 Scenario 按 conversation+week+expected_revision 清空，随后 GET 确认 patches=[]。Conversation/聊天保留作审计，新建空对话没有 Scenario。未批量删除所有 Draft/Scenario，未创建 AAA。

|类型|schedule_id 或 conversation_id|version/revision|client_message_id|结果|
|---|---|---|---|---|
|scenario|conv_70d3b5ed13cc4745995fd1028bf01518|0|—|cleared|
|scenario|conv_1cc0639e603f4153a76c03007c0fff0d|0|—|cleared|
|scenario|conv_e9bb8ac8c8df4be8906e314158b35f0d|1|—|cleared|
|scenario|conv_29695f8a2f3a4328b8c5446d17bde646|1|—|cleared|
|scenario|conv_2242d6aea0ab48b2a3ddf9ee8967a57c|1|—|cleared|
|scenario|conv_295fadec83aa45ec8ae6b14dc1e82eeb|1|—|cleared|
|scenario|conv_5dbf8acbbd2a4d5c8ed7b45f611e8490|0|—|cleared|
|scenario|conv_caabf9023a3245849fe068e8bee975e2|2|—|cleared|
|scenario|conv_75ed9e0b886845e7b052752f22842862|2|—|cleared|
|scenario|conv_1de44a77040e47859c0feb2184a539de|2|—|cleared|
|scenario|conv_aebbc63fc9344a7692fe6b23f0b3a2b1|4|—|cleared|
|scenario|conv_c838afd5e9b74fc49c690518c9d75923|1|—|cleared|
|draft|sch_d4ebb12e79ab|6|cm_1dae4660c27a4a4db51116b6828b64c0|cancelled|
|scenario|conv_20ff2ecc322140ea8a631c2113672b36|0|—|cleared|

生产会话清单：

|Case|conversation_id|
|---|---|
|A|conv_70d3b5ed13cc4745995fd1028bf01518|
|B|conv_1cc0639e603f4153a76c03007c0fff0d|
|C|conv_e9bb8ac8c8df4be8906e314158b35f0d|
|D1|conv_29695f8a2f3a4328b8c5446d17bde646|
|D2|conv_2242d6aea0ab48b2a3ddf9ee8967a57c|
|D3|conv_295fadec83aa45ec8ae6b14dc1e82eeb|
|E|conv_5dbf8acbbd2a4d5c8ed7b45f611e8490|
|X1|conv_caabf9023a3245849fe068e8bee975e2|
|F|conv_75ed9e0b886845e7b052752f22842862|
|X2|conv_1de44a77040e47859c0feb2184a539de|
|G|conv_aebbc63fc9344a7692fe6b23f0b3a2b1|
|G-new-conversation|conv_57cc7a7375884d7a9c68420b84558853|
|C01|conv_c838afd5e9b74fc49c690518c9d75923|
|H|conv_20ff2ecc322140ea8a631c2113672b36|

前两轮生产验收的清理记录（首次完整运行及脚本修复后的G/H定向复测）：

|运行|类型|schedule_id 或 conversation_id|version/revision|client_message_id|结果|
|---|---|---|---|---|---|
|production-browser|scenario|conv_49fb6cbe7f6e4398a9c8a6658d711cd5|0|—|cleared|
|production-browser|scenario|conv_2e4b56730f1a49a282d0d2a93bf976cf|0|—|cleared|
|production-browser|scenario|conv_4101ec34acad4a9c960d35922d53129d|1|—|cleared|
|production-browser|scenario|conv_b50d1e569d464bdba576241d523e4977|1|—|cleared|
|production-browser|scenario|conv_33a994394ff34e0c8b54aded0e2d46a7|1|—|cleared|
|production-browser|scenario|conv_1a00bde1b34049b78da57d3ec51491cb|1|—|cleared|
|production-browser|scenario|conv_adddbbc3b8694409bb278631fb3379e7|0|—|cleared|
|production-browser|scenario|conv_aeed34e4b0674c3a9ae12258e1255aab|2|—|cleared|
|production-browser|scenario|conv_e95a19a99bea4553b1419caad743e162|2|—|cleared|
|production-browser|scenario|conv_db1c457efb63478a85be275707b016b9|2|—|cleared|
|production-browser|scenario|conv_6a2b8c90708147e188001bfb36030fe4|4|—|cleared|
|production-browser|scenario|conv_0dbac96e56c347c7baf96a35e87da351|1|—|cleared|
|production-browser|draft|sch_ea293f0862a4|6|cm_4ae72119d1fa4227ba636211d1abdc0a|cancelled|
|production-browser|scenario|conv_ade95cde39e342ea80201b065b96a680|0|—|cleared|
|production-browser-harness-recheck|scenario|conv_445abb39d4fe48b98b1aaa7322577add|4|—|cleared|
|production-browser-harness-recheck|draft|sch_c4bf76f8d89d|6|cm_1820ad4a0b5246fc9e3a8f88be9c6593|cancelled|
|production-browser-harness-recheck|scenario|conv_6de75f4eea2f48879e0f2d461aeded49|0|—|cleared|

前两轮完整结果和失败详情：[production-prior-runs-audit.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-prior-runs-audit.json)。首次G创建的新空会话在失败后另行只读核查，旧/新会话均无有效Scenario：[production-first-g-audit.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-first-g-audit.json)。全部本轮生产会话的最终复核：[production-final-audit.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-final-audit.json)。


本地临时数据库产生的 Draft/Scenario 不在生产库中。历次本地清理记录：[local-cleanup-audit.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/local-cleanup-audit.json)；早期中断运行定向清理：[local-interrupted-cleanup.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/local-interrupted-cleanup.json)。全部证据和原有未跟踪文件保留，未把运行数据库或 provider 原始输出推到 GitHub。

## Supplemental Hardening Verification

|#|要求|结果|证据/对应测试|涉及文件|
|---|---|---|---|---|
|1|两条 Preview 入口 canonical patch 相同|PASS|test_what_if_and_replan_fallback_have_identical_patches；后端日志|scenario_changes.py、agent_service.py|
|2|legacy 缺shift不使旧conversation崩溃|PASS|test_clear_revision_ownership_idempotency_and_legacy|domain.py、scenarios.py、agent_service.py|
|3|ADD/REMOVE/SET/CLEAR语义|PASS|test_reducer_operation_scopes；线上X1/X2|scenario_changes.py、scenarios.py|
|4|结束试排后F5不恢复|PASS|线上G；scenario-lifecycle.spec.ts|AgentStore.tsx、AppStore.tsx|
|5|新conversation不继承Preview|PASS|线上G；新对话patches为空|AgentStore.tsx|
|6|内部ValidationError为agent_internal_error，不误报422|PASS|test_internal_validation_is_sanitized_and_persisted_safely：普通HTTP500，已建立SSE以error terminal中的status=500结束；missing_shift为澄清|agent_service.py、api/agent.py、main.py|
|7|3次真实重复使用独立conversation|PASS|上方D1/D2/D3请求记录；独立browser context|scenario_acceptance.cjs|
|8|confirmed assignments hash一致|PASS|上方数据保护表；results.json|scenario_acceptance.cjs|
|9|Scenario测试数据准确清理|PASS|上方逐项cleanup；后续GET patches=[]|scenarios.py、scenario_acceptance.cjs|
|10|CloudBase不重复部署|PASS|两次不同commit各由现有CI自动发布一次；无手工deploy、无成功后重复发布相同commit|现有.github/workflows/ci.yml未修改|

## CI/CD 与最终状态

|Job|结果|
|---|---|
|frontend-build|SUCCESS|
|backend-tests|SUCCESS|
|end-to-end-tests|SUCCESS|
|docker-build|SUCCESS|
|deploy-cloudbase|SUCCESS|

最终 CI 后端为364 passed、29 skipped，因为该工作流明确关闭真实LLM；最终 CI E2E为37 passed。上述29项在本地真实Provider环境已全部实际执行并通过，因此本轮真实LLM验收没有跳过。CI日志：[ci-final-backend-tests.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/ci-final-backend-tests.log)、[ci-final-end-to-end-tests.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/ci-final-end-to-end-tests.log)。

CloudBase 安全快照：[cloudbase-after.json](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/cloudbase-after.json)；发布日志：[ci-deploy.log](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/ci-deploy.log)。业务修复先随8eac04f自动发布为043。首次生产验收发现G统计了工作台Markdown、H在聊天异步刷新前计数；修正脚本后G/H线上定向重测通过，再将脚本修正提交为4a5d8ae，由CI自动发布最终main。此后再次全量验收。两次发布对应不同commit，没有任何手工deploy。线上静态资源已核对新版本，随后才运行本报告生产验收。不存在因缺少腾讯云凭据、GitHub权限或CLI造成的阻塞，也没有另行手工重复发布。

关键截图：[M01冲突与退出按钮](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/C.png)、[M02完整条件](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/D3.png)、[修复隔离](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/X1.png)、[新对话正式工作台](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/G.png)、[SSE恢复后的唯一Draft](D:/ee/code/OptiShift-AI/artifacts/scenario-fix/production-browser-final/H.png)。

仍存在的非阻塞事项：CloudBase 默认域名访问提示按用户意见保留；Vite 报单包超过500KB的体积建议；Python测试依赖报告2条弃用警告。M01以及部分Repair仍严格无解属于真实约束结果，已正确展示，不能描述成缺陷或可行Draft。本轮要求无未解决阻塞。

Git工作区没有未提交的跟踪代码变更。运行证据与本报告保留在本地未跟踪目录，原有 diagnose_route.py、report、artifacts、test-results 未被盲目加入提交。本报告自身不触发第二次部署。
