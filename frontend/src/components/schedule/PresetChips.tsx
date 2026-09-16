import { CalendarCheck2, ShieldAlert, Umbrella } from 'lucide-react'

export type PresetId = 'normal' | 'leave' | 'infeasible'

const presets: Array<{ id: PresetId; label: string; detail: string; icon: typeof CalendarCheck2; tone: string }> = [
  { id: 'normal', label: '正常生成', detail: '兼顾偏好与公平', icon: CalendarCheck2, tone: 'text-teal-700 bg-teal-50' },
  { id: 'leave', label: 'E02 临时请假', detail: '周五最小扰动重排', icon: Umbrella, tone: 'text-blue-700 bg-blue-50' },
  { id: 'infeasible', label: '周日店长全请假', detail: '查看不可行诊断', icon: ShieldAlert, tone: 'text-amber-700 bg-amber-50' },
]

export function PresetChips({ onSelect, disabled }: { onSelect(id: PresetId): void; disabled?: boolean }) {
  return (
    <div className="grid gap-2 md:grid-cols-3">
      {presets.map((preset) => {
        const Icon = preset.icon
        return (
          <button
            key={preset.id}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(preset.id)}
            className="group flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left transition hover:border-slate-300 hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${preset.tone}`}><Icon className="h-4 w-4" /></span>
            <span className="min-w-0">
              <span className="block text-xs font-bold text-slate-700">{preset.label}</span>
              <span className="block truncate text-[10px] text-slate-400">{preset.detail}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
