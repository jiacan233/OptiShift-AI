import type { Day, ScheduleStatus, ShiftDelta, ShiftType } from '@/types'
import type { RuleConfig } from '@/api/client'

export const DAY_LABELS: Record<Day, string> = {
  Mon: '周一',
  Tue: '周二',
  Wed: '周三',
  Thu: '周四',
  Fri: '周五',
  Sat: '周六',
  Sun: '周日',
}

export const SHIFT_LABELS: Record<ShiftType, string> = {
  morning: '早班',
  evening: '晚班',
}

export const SHIFT_TIMES: Record<ShiftType, string> = {
  morning: '09:00–17:00',
  evening: '13:00–21:00',
}

export const STATUS_LABELS: Record<ScheduleStatus, string> = {
  draft: '待确认草稿',
  confirmed: '已确认生效',
  cancelled: '已取消',
}

const ROLE_LABELS: Record<string, string> = {
  manager: '店长',
  vice_manager: '副店长',
  shift_leader: '值班主管',
  senior_clerk: '高级店员',
  clerk: '店员',
  part_time: '兼职',
  full_time: '全职员工',
}

const SKILL_LABELS: Record<string, string> = {
  manager: '店长值守',
  beverage: '饮品制作',
  cashier: '收银',
  inventory: '库存管理',
}

export interface RulePresentation {
  name: string
  description: string
}

export const RULE_PRESENTATION: Record<string, RulePresentation> = {
  H01: { name: '每日最多一个班次', description: '每名员工每天最多安排一个班次，重复排班也会被拦截。' },
  R01: { name: '店长值守', description: '每个班次至少 1 名具备店长值守资格的员工。' },
  R02: { name: '饮品制作', description: '每个班次至少 2 名具备饮品制作技能的员工。' },
  R03: { name: '收银', description: '每个班次至少 1 名具备收银技能的员工。' },
  R04: { name: '最低人数', description: '周一至周五每班至少 4 人；周六、周日每班至少 6 人。' },
  R05: { name: '每周最多 5 班 / 40 小时', description: '每人每周最多 40 小时，即最多 5 个班。' },
  R06: { name: '连续工作最多 5 天', description: '不得连续工作超过 5 天。' },
  R07: { name: '晚班后不可次日早班', description: '上一天晚班后不得安排次日早班。' },
  R08: { name: '请假/不可工作日期', description: '请假和不可工作日期绝对不得排班。' },
  R09: { name: '技能来自员工数据', description: '技能必须来自员工数据，Agent 不得自行补技能。' },
  S01: { name: '班次偏好匹配', description: '安排到员工偏好的班次时获得 5 分奖励。' },
  S02: { name: '工作量均衡', description: '员工最大班次差每增加 1 班扣 2 分。' },
  S03: { name: '减少重排影响', description: '临时重排时，每改变一条排班记录扣 8 分。' },
}

const MESSAGE_LABELS: Record<string, string> = {
  Passed: '规则已通过',
  Violation: '规则未通过',
  'No valid schedule exists for the supplied context.': '当前人员和规则条件下无法生成有效排班。',
  'The solver did not return a usable schedule.': '求解器未能返回可用排班。',
  'Assignment references an employee outside master data.': '排班引用了员工主数据中不存在的人员。',
  'Employee has more than one assignment on the same day.': '同一名员工在同一天被安排了多个班次。',
  'Duplicate assignment record is not allowed.': '同一排班记录不能重复。',
  'Manager coverage is below the required minimum.': '店长值守人数低于最低要求。',
  'Beverage coverage is below the required minimum.': '饮品制作人员低于最低要求。',
  'Cashier coverage is below the required minimum.': '收银人员低于最低要求。',
  'Total staffing is below the required minimum.': '当班总人数低于最低要求。',
  'Employee exceeds the weekly shift limit.': '员工的每周班次数超过上限。',
  'Employee works too many consecutive days.': '员工连续工作天数超过上限。',
  'Monday morning follows a previous Sunday evening shift.': '周一早班与上周日晚班连续，休息时间不足。',
  'Morning shift follows an evening shift on the prior day.': '早班紧接前一天晚班，休息时间不足。',
  'Employee is on leave or unavailable on this day.': '员工当天请假或不可工作。',
  'Employee already works the other shift on this day.': '员工当天已经安排了另一个班次。',
  'Employee already reached the weekly shift limit.': '员工已经达到每周班次数上限。',
  'Adding this shift would exceed the consecutive-day limit.': '加入该班次会超过连续工作天数上限。',
  'The request explicitly removes this assignment.': '本次调整明确要求移除该排班。',
  'Adding this employee requires other assignment changes that violate a retained hard rule.': '加入该员工会引发其他调整，并违反需要保留的硬约束。',
  'The previous confirmed Sunday evening blocks Monday morning.': '上一份正式排班中的周日晚班会阻止该员工继续上周一早班。',
  'Employee works the preceding evening shift.': '员工前一天已安排晚班。',
  'Employee works the following morning shift.': '员工后一天已安排早班。',
}

export function roleLabel(role: string) {
  return ROLE_LABELS[role] ?? '员工'
}

export function skillLabel(skill: string) {
  return SKILL_LABELS[skill] ?? '已登记技能'
}

export function rulePresentation(ruleId: string, fallback?: Partial<RulePresentation>, config?: RuleConfig): RulePresentation {
  const copy = RULE_PRESENTATION[ruleId] ?? {
    name: fallback?.name && containsChinese(fallback.name) ? fallback.name : '排班规则',
    description: fallback?.description && containsChinese(fallback.description) ? fallback.description : '该规则由后端规则中心统一提供。',
  }
  if (!config) return copy
  const descriptions: Record<string, string> = {
    R01: `每个班次至少需要 ${config.manager_per_shift} 名具备店长值守资格的员工。`,
    R02: `每个班次至少需要 ${config.beverage_per_shift} 名具备饮品制作技能的员工。`,
    R03: `每个班次至少需要 ${config.cashier_per_shift} 名具备收银技能的员工。`,
    R04: `工作日每班至少 ${config.weekday_min_staff} 人，周末每班至少 ${config.weekend_min_staff} 人。`,
    R05: `每名员工每周最多安排 ${config.max_shifts_per_week} 个班次。`,
    R06: `连同上周边界计算，每名员工最多连续工作 ${config.max_consecutive_days} 天。`,
  }
  return { ...copy, description: descriptions[ruleId] ?? copy.description }
}

export function localizeMessage(message: string | undefined, fallback: string) {
  if (!message) return fallback
  if (containsChinese(message)) return message
  if (MESSAGE_LABELS[message]) return MESSAGE_LABELS[message]

  const availability = message.match(/^Only (\d+) available (.+) qualified staff for a requirement of (\d+)\.$/)
  if (availability) {
    const [, actual, skill, required] = availability
    return `符合条件的${skillLabel(skill)}员工只有 ${actual} 人，需要 ${required} 人。`
  }
  const staffing = message.match(/^Only (\d+) employees are available for a requirement of (\d+)\.$/)
  if (staffing) return `当前只有 ${staffing[1]} 名员工可上班，需要 ${staffing[2]} 名。`

  return fallback
}

export function ruleCheckMessage(ruleId: string, passed: boolean, message?: string) {
  const rule = rulePresentation(ruleId)
  if (message === 'Passed') return `${rule.name}：已通过`
  if (message?.includes('; ')) {
    return message.split('; ').map((item) => localizeMessage(item, `${rule.name}未通过`)).join('；')
  }
  return localizeMessage(message, passed ? `${rule.name}：已通过` : `${rule.name}：未通过`)
}

export function shiftReference(item: ShiftDelta | string) {
  if (typeof item !== 'string') return `${DAY_LABELS[item.day]}${SHIFT_LABELS[item.shift]}`
  if (/^E\d+$/i.test(item)) return `员工 ${item}`
  const match = item.match(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(morning|evening)\b/)
  if (!match) return containsChinese(item) ? item : '相关班次'
  return `${DAY_LABELS[match[1] as Day]}${SHIFT_LABELS[match[2] as ShiftType]}`
}

export function errorCodeLabel(code: string) {
  const labels: Record<string, string> = {
    network_error: '网络连接异常',
    entity_not_found: '未找到员工',
    conversation_not_found: '未找到这条对话',
    version_conflict: '排班版本冲突',
    history_unavailable: '缺少上一周排班历史',
    draft_pending: '已有待确认草稿',
    suggestion_stale: '建议已失效',
    ai_unavailable: 'AI 助手暂时不可用',
    agent_turn_timeout: '本轮处理超时',
    invalid_agent_action: 'Agent 操作无效',
    agent_operation_failed: 'Agent 操作失败',
    message_processing: '消息仍在处理中',
    conversation_busy: '当前对话正在处理另一条消息',
    turn_interrupted: '先前请求已中断',
    validation_error: '请求校验未通过',
    solver_unavailable: '排班求解服务不可用',
    solver_unknown: '求解状态异常',
    base_schedule_required: '缺少正式排班',
    internal_error: '服务内部异常',
    unknown: '未知异常',
  }
  return labels[code] ?? '操作异常'
}

export function problemMessage(code: string, message?: string) {
  if (code === 'ai_unavailable') {
    return message?.trim() || 'AI 助手暂时不可用，请稍后重试。'
  }
  const messages: Record<string, string> = {
    agent_turn_timeout: '本轮处理超过执行预算，已保存的草稿会保留，请查看执行进度。',
    history_unavailable: '目标周缺少上一周已确认排班，因此无法安全校验连续工作天数和晚班转早班规则。请补充上一周排班或选择连续的排班周次。',
    draft_pending: '当前已有待确认草稿，请先确认或取消当前草稿。',
    version_conflict: '正式排班已经更新，请刷新当前周后再试。',
    suggestion_stale: '这条建议所依据的排班已经变化，请重新获取建议。',
    message_processing: '同一条消息仍在服务端处理中，请稍后使用原请求标识重试。',
    conversation_busy: '当前对话正在处理另一条消息，请等待完成后再发送。',
    turn_interrupted: '先前请求在服务中断后未完成，请重新发送。',
  }
  return messages[code] ?? localizeMessage(message, '请求未完成，请稍后重试。')
}

export const AGENT_STAGE_LABELS: Record<string, string> = {
  agent_route: '理解排班请求', intent_parse: '解析排班调整', explanation: '生成排班说明',
  response_compose: '生成回复', structured_output_health: '检测结构化输出',
  agent_route_lite: 'Agent Router', agent_mutation: '解析排班变更', agent_force: '解析例外授权', router_fallback: '备用 JSON 解析', structured_output: '检测结构化输出', basic_chat: '检测基础聊天',
  resolve_context: '定位排班上下文', load_schedule: '读取当前排班', load_employees: '读取员工信息',
  solver: '计算排班方案', validator: '校验排班规则', save_draft: '保存排班草稿', tool: '执行排班操作',
}

export function problemDetail(_code: string, details?: unknown) {
  if (!details || typeof details !== 'object') return null
  const source = details as Record<string, unknown>
  const parts: string[] = []
  if (typeof source.stage === 'string') parts.push(`阶段：${AGENT_STAGE_LABELS[source.stage] ?? '处理排班请求'}`)
  if (typeof source.latency_ms === 'number') parts.push(`耗时：${(source.latency_ms / 1000).toFixed(1)} 秒`)
  if (typeof source.provider_status === 'number') parts.push(`HTTP ${source.provider_status}`)
  if (typeof source.error_type === 'string') parts.push(`类型：${source.error_type}`)
  if (typeof source.provider_message === 'string' && source.provider_message.trim()) parts.push(source.provider_message)
  return parts.join(' · ') || null
}

function containsChinese(value: string) {
  return /[\u3400-\u9fff]/.test(value)
}
