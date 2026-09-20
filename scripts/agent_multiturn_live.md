# 真实多轮 HTTP/SSE 验收

默认离线测试不会启动此入口。脚本从仓库 `.env` / 进程环境读取现有
`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`，子进程设置 `LLM_ENABLED=true`。
不会打印或写入密钥，不会更换 Provider，不会提升业务超时预算。

```powershell
# 仅准备基线，不调用 Provider
.\.venv\Scripts\python.exe scripts/agent_multiturn_live.py --prepare-only

# 完整原句 A–N，每 case 独立 SQLite + 应用进程 + 随机本地端口
.\.venv\Scripts\python.exe scripts/agent_multiturn_live.py --cases A-N

# 可以复用已准备的基线；每次运行和每 case 仍复制为独立数据库
.\.venv\Scripts\python.exe scripts/agent_multiturn_live.py --cases A,B,E,G,H,J --repeat 2 `
  --baseline-dir artifacts/agent-multiturn-live/<fixture-run-id>/baseline

# 同一验收器的自然语言变体（只替换消息措辞，继承原 A/B/E/G/H/J 断言）
.\.venv\Scripts\python.exe scripts/agent_multiturn_live.py --cases A,B,E,G,H,J `
  --natural-variants --repeat 2 `
  --baseline-dir artifacts/agent-multiturn-live/<fixture-run-id>/baseline

# 判定器离线回归
.\.venv\Scripts\python.exe -m pytest tests/evals/test_multiturn_harness.py -q
```

基线使用真实 E01–E20 主数据和正常硬规则，以真实 Solver、独立 Validator 和
确认流程准备 2026-09-28、2026-10-05 两周正式排班。对话开始时没有草稿和
Scenario/Pending/建议。H 另外构造经过独立校验的合法不均衡基线，并保存至少
一条合法改善见证。基线生成结束后不再写入待测业务数据；所有多轮消息经过
正常 HTTP/SSE 入口。

每次运行创建新的 `artifacts/agent-multiturn-live/<UTC>-<uuid>/`，不复用证据目录：

- `manifest.json`：代码 SHA、tracked diff hash、源码文件 hash、脱敏配置。
- `baseline/*.json`：固定员工、规则、历史、排班和 H 可改善性证明。
- `CASE_*/turn-*.json`、`*.sse`：完整请求身份、终态事件、逐轮全表只读快照、
  工具输入输出、Provider 请求记录和分阶段耗时。
- `CASE_*/provider.jsonl`：真实 `_post` 调用 stage、model、服务域名 hash、
  conversation/client ID、成功/失败和耗时；不记录请求 prompt 或隐藏推理。
- `CASE_*/backend.log`、`transcript.json`、`final-state.json`、`summary.json`：
  完整过程与失败检查；JSON 不裁切。

只有收到当前消息的 SSE 终态、数据库助手回复，并确认会话 lease 已释放后才
发送下一轮。HTTP 200、旧卡片、旧草稿、正文中的“生成成功”均不作为通过证据。
检查器独立核对预期条件、中间 Pending/提案/纠正、求解 requested_changes、
Validator、当轮新 Draft 来源及 revision/hash。

退出码 0 仅表示所选 HTTP 合约通过且有连续会话的多个真实 Provider 业务轮证据；
它不代表完整验收。浏览器刷新、截图、卡片和工作台门禁需要另外运行浏览器检查。
J5 在 HTTP runner 中仅用重新 GET 会话记录服务端恢复，明确标记 UI 未验证。
最终 `complete_acceptance` 保持 false，直到这些检查和逐 case 语义复核完成。

阶段耗时互有嵌套，不能相加。HTTP 总耗时从发出 POST 至 SSE 关闭；settled 总耗时
另含数据库终态轮询。Provider 失败、产品断言失败、验收器失败分别保留，失败重跑
必须创建新 run ID。SQLite 已覆盖，MySQL 并发行为需另行验证。
