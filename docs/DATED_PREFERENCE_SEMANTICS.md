# 按日偏好执行语义

员工档案中的 `preferred_shift` 是全周默认班次偏好。临时 `PREFERENCE`
始终带有 `day`，仅覆盖指定日的默认偏好，其它日继续使用档案默认值。
例如默认晚班，临时周四早班优先、周日晚班优先，则周四只奖励早班，
其余六日只奖励晚班；周日晚班不会因为同时命中默认值而获得双重奖励。

`SchedulingFacts` 用不可变日期/班次集合保存临时偏好，并按固定日期、班次顺序
编译目标项。重复请求去重；交换不同日期请求的输入顺序不会改变目标系数。
同一天有多个软偏好时，任意被列出的班次均可满足当天偏好，最多获得一次奖励；
H01 仍禁止同日双班。需要精确纠正某条偏好时，由上层条件归约器先移除旧条件、
再添加新条件，求解器不会用新请求覆盖同员工其它日期的条件。

偏好不授予可用性，也不强制排班。请假、不可排、UNASSIGN 及其它硬约束优先。
明确请求已纳入目标，并不代表最终排班一定满足；最小改动等其它软目标也可能
使 Solver 保留原安排。

主求解、授权例外求解的业务目标阶段和不可行诊断的业务目标阶段，共用
`ConstraintBuilder.preference_terms`。每个有效偏好槽位的奖励为
`rules.objective.preference_reward`，没有跨日奖励。

`preference_satisfied` 统计实际排入偏好班次的员工-日期数；
`preference_opportunities` 统计存在有效默认或按日偏好的员工-日期数。
未排班、请假导致无法满足的日期仍在分母内。`preference_rate` 是二者之比，
没有偏好时为 1，`preference_scope=effective_employee_days` 标明此口径。
这与旧版只统计已排班员工的分母不同，避免未满足的明确请求从分母消失。
`day_preference_satisfied`、`day_preference_opportunities`、`day_preference_rate`
以相同口径单独展示临时按日请求，不将其它日期的默认偏好算作满足了该请求。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_day_preferences.py tests/test_solver.py tests/test_constraints.py tests/test_boundary_context.py tests/test_overrides.py -q
```

按日偏好回归直接检查 CP-SAT 目标系数，并在仅含一位员工、没有覆盖需求且
最多工作两班的小实例中真实求解，验证周四早班与周日晚班同时生效及输入顺序等价。

## 班次级可用性

`AVAILABLE`、`UNAVAILABLE` 和 `LEAVE` 的可选 `shift` 表示准确班次范围。
无班次仍表示整日。整日不可排与明确晚班可用共存时，晚班可用是仅针对该槽位
的例外，早班仍不可排。显式同槽不可排优先于矛盾的同槽可用；上层应澄清此冲突。
可用性不会产生 ASSIGN，也不会修改员工档案或突破 H01 等硬约束。
Solver、独立 Validator、局部容量预检、不可行候选说明都查询相同的班次范围。

`tests/test_shift_availability.py` 覆盖仅恢复晚班、顺序等价、无需强制安排、
独立校验拒绝早班、周日早班仍缺 manager 的真实不可行结果，以及 H01 保护。
