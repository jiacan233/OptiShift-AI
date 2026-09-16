import { UserRound, X } from 'lucide-react'
import type { ClarificationState } from '@/types'

export function EntityClarifier({ clarification, onChoose, onClose }: { clarification: ClarificationState | null; onChoose(id: string): void; onClose(): void }) {
  if (!clarification) return null
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4 backdrop-blur-sm">
      <section className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-drawer" role="dialog" aria-modal="true" aria-label="选择员工">
        <div className="flex items-start justify-between gap-4">
          <div><p className="eyebrow">需要澄清</p><h2 className="mt-2 text-xl font-extrabold text-ink">请选择你指的员工</h2><p className="mt-2 text-sm text-slate-500">{clarification.prompt}</p></div>
          <button onClick={onClose} className="rounded-xl border border-slate-200 p-2 text-slate-500"><X className="h-4 w-4" /></button>
        </div>
        <div className="mt-5 space-y-2">
          {clarification.candidates.map((candidate) => (
            <button key={candidate.employee_id} onClick={() => onChoose(candidate.employee_id)} className="flex w-full items-center gap-3 rounded-xl border border-slate-200 p-3 text-left transition hover:border-teal-400 hover:bg-teal-50">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-600"><UserRound className="h-5 w-5" /></span>
              <span><span className="block text-sm font-extrabold text-slate-800">{candidate.employee_id}</span><span className="block text-xs capitalize text-slate-500">{candidate.role}</span></span>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}

