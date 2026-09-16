import { CheckCircle2, Clock3, FileEdit } from 'lucide-react'
import type { ScheduleVersion } from '@/types'

export function VersionHistory({ versions }: { versions: ScheduleVersion[] }) {
  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between"><div><p className="eyebrow">Version History</p><h3 className="mt-1 text-base font-extrabold text-ink">排班版本</h3></div><Clock3 className="h-5 w-5 text-slate-400" /></div>
      <div className="mt-4 space-y-2">
        {versions.map((item) => (
          <div key={item.schedule_id} className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2.5">
            {item.status === 'confirmed' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <FileEdit className="h-4 w-4 text-amber-600" />}
            <div className="min-w-0 flex-1"><p className="text-xs font-extrabold text-slate-700">v{item.version} · {item.status}</p><p className="truncate text-[10px] text-slate-400">{new Date(item.created_at).toLocaleString()} · parent {item.parent_schedule_id ?? '—'}</p></div>
          </div>
        ))}
        {versions.length === 0 && <p className="text-xs text-slate-400">确认排班后会显示版本历史。</p>}
      </div>
    </section>
  )
}
