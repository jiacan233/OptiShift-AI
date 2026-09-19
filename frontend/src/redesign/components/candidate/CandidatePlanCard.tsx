import type { CandidatePlan } from './types'

// Visual structure and classes migrated from optishift-ui-demo/CandidatePlanCard.
export function CandidatePlanCard({ plan, isSelected, onSelect, disabled }: {
  plan: CandidatePlan
  isSelected: boolean
  onSelect(id: string): void
  disabled: boolean
}) {
  return (
    <button type="button" aria-pressed={isSelected} disabled={disabled} onClick={() => onSelect(plan.id)}
      className={`relative w-full text-left p-2.5 rounded-xl border transition-all duration-150 flex items-start gap-2.5 outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 ${isSelected ? 'bg-blue-50/70 border-blue-500 shadow-xs ring-1 ring-blue-500/20' : 'bg-white border-slate-200/80 hover:border-slate-300 hover:bg-slate-50/70'}`}>
      <div className="mt-0.5 shrink-0">
        <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center transition-colors ${isSelected ? 'border-blue-600 bg-white ring-2 ring-blue-100' : 'border-slate-300 bg-white'}`}>
          {isSelected && <div className="w-2 h-2 rounded-full bg-blue-600" />}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-xs font-extrabold tracking-tight ${isSelected ? 'text-blue-900' : 'text-slate-800'}`}>{plan.name}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold tracking-tight ${isSelected ? 'bg-blue-100/90 text-blue-700' : 'bg-slate-100 text-slate-500'}`}>{plan.tag}</span>
        </div>
        <p className={`text-[11px] mt-0.5 truncate leading-tight ${isSelected ? 'text-blue-700/80 font-medium' : 'text-slate-400'}`} title={plan.subtitle}>{plan.subtitle}</p>
      </div>
    </button>
  )
}
