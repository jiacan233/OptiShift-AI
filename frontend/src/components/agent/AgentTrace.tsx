import { ChevronDown, Wrench } from 'lucide-react'
import type { AgentToolCall } from '@/types'

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
  generate_schedule: '已调用确定性排班求解器',
  replan_schedule: '已调用确定性重排求解器',
}

export function AgentTrace({ calls }: { calls: AgentToolCall[] }) {
  if (!calls.length) return null
  return (
    <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 text-xs text-slate-600">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 font-bold text-slate-600">
        <Wrench className="h-3.5 w-3.5 text-teal-600" />
        分析过程
        <ChevronDown className="ml-auto h-3.5 w-3.5" />
      </summary>
      <div className="space-y-2 border-t border-slate-200 px-3 py-2.5">
        {calls.map((call) => (
          <div key={call.tool_call_id} className="flex items-start gap-2">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${call.status === 'completed' || call.status === 'success' ? 'bg-emerald-500' : 'bg-slate-400'}`} />
            <p>{call.output_summary || TOOL_LABELS[call.tool_name] || `已调用 ${call.tool_name}`}</p>
          </div>
        ))}
      </div>
    </details>
  )
}
