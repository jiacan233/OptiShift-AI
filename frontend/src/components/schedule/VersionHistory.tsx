import { CheckCircle2, Clock3, FileEdit } from 'lucide-react'
import { STATUS_LABELS } from '@/lib/presentation'
import type { ScheduleVersion } from '@/types'
import { ViolationDetails } from './ViolationDetails'

export function VersionHistory({ versions }: { versions: ScheduleVersion[] }) {
  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between"><div><p className="eyebrow">版本记录</p><h3 className="mt-1 text-base font-extrabold text-ink">当前周版本记录</h3></div><Clock3 className="h-5 w-5 text-slate-400" /></div>
      <div className="mt-4 space-y-2">
        {versions.map((item) => (
          <div key={item.schedule_id} className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2.5">
            {item.status === 'confirmed' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <FileEdit className="h-4 w-4 text-amber-600" />}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-extrabold text-slate-700">版本 {item.version} · {STATUS_LABELS[item.status]}</p>
              {item.compliance_status && <p className={`mt-1 text-[11px] font-bold ${item.compliance_status === 'compliant' ? 'text-emerald-700' : item.compliance_status === 'authorized_violations' ? 'text-amber-700' : 'text-red-700'}`}>{item.compliance_status === 'compliant' ? '合规' : item.compliance_status === 'authorized_violations' ? `存在 ${item.authorized_violation_count ?? 0} 项已接受规则例外` : '存在规则冲突'}</p>}
              <p className="truncate text-[10px] text-slate-400">{new Date(item.created_at).toLocaleString('zh-CN')} · 上一版本 {item.parent_schedule_id ?? '—'}</p>
              {!!item.violations?.length && <details className="mt-2">
                <summary className="cursor-pointer text-xs font-bold text-amber-700">查看此版本的规则例外</summary>
                <div className="mt-2"><ViolationDetails violations={item.violations} /></div>
              </details>}
            </div>
          </div>
        ))}
        {versions.length === 0 && <p className="text-xs text-slate-400">确认排班后会显示版本历史。</p>}
      </div>
    </section>
  )
}
