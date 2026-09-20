# 真实 LLM 用例审计

本轮 29/29 用例通过，包含原有 25 项与新增 4 项；无跳过。逐项有真实 Provider HTTP 200，并验证测试数据库无写入。模型：gpt-5.6-sol。

|用例|结果|Provider HTTP|数据库未改变|
|---|---|---|---|
|busiest_employee|PASS|200|是|
|current_rule_violations|PASS|200|是|
|e01_monday_absence|PASS|200|是|
|e03_wednesday_absence|PASS|200|是|
|e15_sunday_assignment|PASS|200|是|
|explicit_history_optout|PASS|200|是|
|explicit_second_suggestion|PASS|200|是|
|one_fewer_sunday_morning|PASS|200|是|
|previous_version_diff|PASS|200|是|
|remove_e07_evening|PASS|200|是|
|router-e01_leave_replan|PASS|200|是|
|router-e17_feasibility|PASS|200|是|
|router-e17_unspecified|PASS|200|是|
|router-explicit_force_r08|PASS|200|是|
|router-force_missing_scope|PASS|200|是|
|router-hello|PASS|200|是|
|router-multi_employee_days|PASS|200|是|
|router-negative_force|PASS|200|是|
|router-only_leave_followup|PASS|200|是|
|router-ordered_operations|PASS|200|是|
|router-preference_missing_shift|PASS|200|是|
|router-previous_suggestion|PASS|200|是|
|router-set_preserves_preference|PASS|200|是|
|router-sunday_staffing|PASS|200|是|
|router-two_preference_shifts|PASS|200|是|
|sun_assignments|PASS|200|是|
|sun_evening_beverage|PASS|200|是|
|sun_staffing_after_previous_suggestion|PASS|200|是|
|why_infeasible|PASS|200|是|

原始结构化输出与各阶段耗时见 full-live-evidence/case-*.json。全量后端日志：all-tests-live-enabled.log（393 passed，0 skipped）。
