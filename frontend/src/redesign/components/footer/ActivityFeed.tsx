import type { ScheduleVersion } from '@/types'
import { STATUS_LABELS } from '@/lib/presentation'

export function ActivityFeed({ versions }: { versions: ScheduleVersion[] }) {
  const recent = [...versions].sort((a, b) => b.version - a.version).slice(0, 3)
  return <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm flex-1">
    <h3 className="text-sm font-bold text-slate-900">最近排班版本</h3>
    <div className="mt-4 space-y-3 text-xs">
      {recent.length ? recent.map(version => <div key={version.schedule_id} className="flex flex-wrap justify-between gap-2">
        <span className="font-semibold text-slate-700">v{version.version} · {STATUS_LABELS[version.status]}</span>
        <time className="text-slate-400" dateTime={version.created_at}>{new Date(version.created_at).toLocaleString('zh-CN')}</time>
      </div>) : <p className="text-slate-400">暂无版本记录</p>}
    </div>
  </section>
}
