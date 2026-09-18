import type { Violation } from '@/types'
import { DAY_LABELS, SHIFT_LABELS } from '@/lib/presentation'

export function ViolationDetails({ violations }: { violations: Violation[] }) {
  return <div className="space-y-2">{violations.map((item) => <div key={item.violation_id} className={`rounded-xl border p-3 text-xs leading-6 ${item.authorized ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-red-200 bg-red-50 text-red-900'}`}>
    <p className="font-extrabold">{item.rule_id} {item.rule_name} · {item.authorized ? '已授权例外' : '未授权冲突'}</p>
    <p>{item.day ? DAY_LABELS[item.day] : ''} {item.shift ? SHIFT_LABELS[item.shift] : ''} {item.employee_id ?? ''}</p>
    {item.rule_id === 'R08' ? <p>{item.employee_id} 原本该日请假或不可用，本次{item.authorized ? '按用户明确授权' : '未经授权'}安排该班次。</p> : <p>要求：{item.expected ?? '—'} · 实际：{item.actual ?? '—'}{item.shortage != null ? ` · 缺口：${item.shortage}` : ''}</p>}
    {item.authorization_id && <p className="break-all text-[10px]">授权记录：{item.authorization_id}</p>}
  </div>)}</div>
}
