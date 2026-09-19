import type { WeekMetrics } from '../../utils/scheduleSelectors'

export function AttendanceCard({ metrics }: { metrics: WeekMetrics }) {
  return <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm flex-1">
    <h3 className="text-sm font-bold text-slate-900">本周人员安排</h3>
    <dl className="mt-4 grid grid-cols-3 gap-3 text-xs text-slate-500">
      <div><dt>已排班</dt><dd className="mt-2 text-xl font-bold text-blue-600">{metrics.assignedEmployeesCount} 人</dd></div>
      <div><dt>未排班</dt><dd className="mt-2 text-xl font-bold text-slate-800">{metrics.zeroShiftEmployeesCount} 人</dd></div>
      <div><dt>在册请假</dt><dd className="mt-2 text-xl font-bold text-slate-800">{metrics.totalLeaveEmployees} 人</dd></div>
    </dl>
    <p className="mt-4 text-xs text-slate-400">根据当前周排班与员工档案统计；实际考勤尚未接入。</p>
  </section>
}
