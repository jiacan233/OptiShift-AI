import { ChevronDown, Wrench, CheckCircle2, XCircle, LoaderCircle, Circle } from 'lucide-react'
import type { AgentExecutionEvent, AgentToolCall } from '@/types'

const TOOL_LABELS: Record<string, string> = {
  get_current_schedule: '已读取当前周正式排班与草稿',
  load_schedule_context: '已读取当前周排班上下文',
  get_schedule_context: '已读取当前周排班上下文',
  get_employee: '已读取员工主数据',
  get_rules: '已读取排班规则',
  load_employees: '已读取员工主数据',
  list_employees: '已读取员工主数据',
  load_rules: '已读取排班规则',
  list_rules: '已读取排班规则',
  validate_schedule: '已调用排班校验器',
  analyze_schedule: '已分析当前排班',
  analyze_staffing: '已计算人数、技能覆盖和排班事实',
  analyze_counterfactual: '已只读验证移除和替代方案，未修改排班',
  generate_schedule: '已调用确定性排班求解器',
  replan_schedule: '已调用确定性重排求解器',
}

export function AgentTrace({ calls, events = [], running = false }: {
  calls: AgentToolCall[]; events?: AgentExecutionEvent[]; running?: boolean
}) {
  const stages = new Map<string, AgentExecutionEvent>()
  events.filter((event) => event.stage !== 'tool').forEach((event) => stages.set(event.operation_id, event))
  if (!calls.length && !events.length && !running) return null
  return (<>
    {running && stages.size === 0 && <p role="status" className="mt-3 flex items-center gap-2 rounded-xl border border-blue-100 bg-blue-50/50 p-3 text-xs text-blue-700"><LoaderCircle className="h-4 w-4 animate-spin" />请求处理中，等待执行进度…</p>}
    {stages.size > 0 && <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50/50 p-3"><p className="mb-2 text-[11px] font-bold text-blue-800">处理进度 · 公开执行记录</p><ol aria-label="执行进度" aria-live="polite" className="space-y-2 text-[11px] text-slate-600">
      {[...stages.values()].map((event) => {
        const active = event.status === 'started'
        const failed = event.status === 'failed'
        const Icon = failed ? XCircle : active ? (running ? LoaderCircle : Circle) : CheckCircle2
        const days: Record<string, string> = { Mon: '周一', Tue: '周二', Wed: '周三', Thu: '周四', Fri: '周五', Sat: '周六', Sun: '周日' }
        const changes = event.details.changes?.filter((change) => change.type === 'leave').map((change) => `${change.employee_id} ${days[change.day] ?? change.day}请假`).join('，')
        return <li key={event.operation_id} className="flex items-start gap-2">
          <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${failed ? 'text-red-500' : 'text-blue-600'} ${active && running ? 'animate-spin' : ''}`} />
          <div><p>{event.label}{active ? (running ? '…' : '（等待恢复进度）') : event.stage.startsWith('turn_') ? '' : failed ? (event.label.endsWith('失败') ? '' : '失败') : (event.label.endsWith('完成') ? '' : '完成')}{event.duration_ms != null && <span className="ml-1 text-slate-400">{event.duration_ms} ms</span>}</p>
            {changes && <p className="mt-0.5 text-blue-700">{changes}</p>}
            {event.details.target_week && <p className="mt-0.5">目标周：{event.details.target_week}</p>}
            {event.details.error_type && <p className="mt-0.5 text-red-600">{({ read_timeout: '等待 AI 响应超时', connect_timeout: '连接 AI 服务超时', agent_turn_timeout: '本轮执行超过时间预算', solver_timeout: '排班求解超时' } as Record<string, string>)[event.details.error_type] ?? '当前步骤未完成'}</p>}
          </div>
        </li>
      })}
    </ol></div>}
    {calls.length > 0 && (
    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 text-xs text-slate-600">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 font-bold text-slate-600">
        <Wrench className="h-3.5 w-3.5 text-blue-600" />
        工具执行记录
        <ChevronDown className="ml-auto h-3.5 w-3.5" />
      </summary>
      <div className="space-y-2 border-t border-slate-200 px-3 py-2.5">
        {calls.map((call) => (
          <div key={call.tool_call_id} className="flex items-start gap-2">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${call.status === 'completed' || call.status === 'success' ? 'bg-emerald-500' : 'bg-slate-400'}`} />
            <div className="min-w-0 flex-1"><p className="break-words">{call.output_summary || TOOL_LABELS[call.tool_name] || `已调用 ${call.tool_name}`}</p>
              <p className="mt-1 break-all text-[10px] text-slate-400">{call.tool_name} · {call.status}{call.created_at && call.finished_at && Number.isFinite(Date.parse(call.finished_at) - Date.parse(call.created_at)) ? ` · ${Math.max(0, Date.parse(call.finished_at) - Date.parse(call.created_at))} ms` : ''}</p>
              <details className="mt-1"><summary className="cursor-pointer text-[10px] text-blue-600">调用详情</summary><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-white p-2 text-[10px]">{JSON.stringify({ input: call.input_json, output: call.output_json }, null, 2)}</pre></details>
            </div>
          </div>
        ))}
      </div>
    </details>)}
  </>)
}
