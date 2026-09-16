import { CalendarPlus, MessageSquareText, Umbrella } from 'lucide-react'
import type { RunAction } from '@/types'

const actions: Array<{ id: RunAction; label: string; hint: string; icon: typeof CalendarPlus }> = [
  { id: 'generate', label: '生成新排班', hint: '创建本周草稿', icon: CalendarPlus },
  { id: 'leave', label: '临时请假', hint: '基于正式版重排', icon: Umbrella },
  { id: 'freeform', label: '自由输入', hint: '用自然语言描述', icon: MessageSquareText },
]

export function ActionSelector({ value, onChange }: { value: RunAction; onChange(value: RunAction): void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="选择排班操作">
      {actions.map((action) => {
        const Icon = action.icon
        const selected = value === action.id
        return (
          <button
            key={action.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(action.id)}
            className={`flex items-center gap-3 rounded-xl border px-3 py-3 text-left transition ${selected ? 'border-teal-500 bg-teal-50 text-teal-800 ring-1 ring-teal-500/20' : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'}`}
          >
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${selected ? 'bg-teal-600 text-white' : 'bg-slate-100 text-slate-500'}`}>
              <Icon className="h-[18px] w-[18px]" />
            </span>
            <span>
              <span className="block text-sm font-bold">{action.label}</span>
              <span className="block text-[11px] text-slate-500">{action.hint}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
