import React from 'react'
import { AlertTriangle, ShieldAlert, UserX, X, HelpCircle, ArrowRight } from 'lucide-react'

interface ConflictBannerProps {
  onClose: () => void
  onAskAiToResolve?: () => void
  blockedCandidates?: {
    employeeId: string
    name: string
    reason: string
    violatedRule: string
  }[]
}

const DEFAULT_BLOCKED_CANDIDATES = [
  {
    employeeId: 'E03',
    name: 'E03 (值班主管)',
    reason: '当日处于不可用休息状态，不可安排早班值守',
    violatedRule: 'R-08',
  },
  {
    employeeId: 'E05',
    name: 'E05 (高级店员)',
    reason: '周日晚班接周一早班，间隔不足 11h，触发晚转早防疲劳约束',
    violatedRule: 'R-06',
  },
  {
    employeeId: 'E08',
    name: 'E08 (店员)',
    reason: '已连续工作 5 天，继续排班将违反每周最大连续出勤约束',
    violatedRule: 'R-05',
  },
]

export const ConflictBanner: React.FC<ConflictBannerProps> = ({
  onClose,
  onAskAiToResolve,
  blockedCandidates = DEFAULT_BLOCKED_CANDIDATES,
}) => {
  return (
    <div className="bg-rose-50/90 border border-rose-200/80 rounded-3xl p-5 shadow-sm text-slate-800 space-y-4 animate-fade-in backdrop-blur-sm">
      {/* Top Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-2xl bg-rose-500 text-white flex items-center justify-center shrink-0 shadow-md shadow-rose-500/20">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-extrabold uppercase tracking-wider text-rose-600 bg-rose-100 px-2.5 py-0.5 rounded-full">
                排班求解结果 · 当前不可行
              </span>
              <span className="text-xs font-semibold text-slate-400">已保护现有正式排班不受污染</span>
            </div>
            <h3 className="text-base font-extrabold text-slate-900 mt-1">
              系统未生成违规排班
            </h3>
            <p className="text-xs text-rose-700/90 mt-0.5">
              当前人员可用性与技能组合无法同时满足全部硬约束。底层 CP-SAT 求解器已自动中断并生成精确阻挡归因报告。
            </p>
          </div>
        </div>

        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 p-1.5 rounded-xl hover:bg-rose-100/50 transition"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Grid: Left Coverage Gaps, Right Candidate Blockage Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-1">
        {/* Left: 覆盖缺口 */}
        <div className="bg-white rounded-2xl p-4 border border-rose-200/60 shadow-xs space-y-3">
          <div className="flex items-center justify-between text-xs font-bold text-slate-800 border-b border-slate-100 pb-2">
            <span className="flex items-center gap-1.5 text-rose-600">
              <AlertTriangle className="w-4 h-4" /> 覆盖缺口 (Coverage Gaps)
            </span>
            <span className="text-[11px] text-rose-500 font-semibold bg-rose-50 px-2 py-0.5 rounded-md">
              缺少 1 人
            </span>
          </div>

          <div className="space-y-2">
            <div className="p-2.5 rounded-xl bg-rose-50/50 border border-rose-100/80 flex items-center justify-between">
              <div>
                <div className="text-xs font-extrabold text-slate-900">
                  R-01 · 店长值守覆盖
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  周一 · 早班 (09:00 - 17:00)：需要 ≥ 1 人，当前可用 0 人
                </div>
              </div>
              <span className="text-xs font-bold text-rose-600 bg-white px-2 py-1 rounded-lg border border-rose-200">
                缺口 -1
              </span>
            </div>

            <div className="p-2.5 rounded-xl bg-rose-50/50 border border-rose-100/80 flex items-center justify-between">
              <div>
                <div className="text-xs font-extrabold text-slate-900">
                  R-04 · 门店在岗人数
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  周一 · 早班：底线 4 人，排除冲突后仅余 3 人
                </div>
              </div>
              <span className="text-xs font-bold text-rose-600 bg-white px-2 py-1 rounded-lg border border-rose-200">
                缺口 -1
              </span>
            </div>
          </div>
        </div>

        {/* Right: 候选人阻挡分析 */}
        <div className="bg-white rounded-2xl p-4 border border-rose-200/60 shadow-xs space-y-3">
          <div className="flex items-center justify-between text-xs font-bold text-slate-800 border-b border-slate-100 pb-2">
            <span className="flex items-center gap-1.5 text-amber-600">
              <UserX className="w-4 h-4" /> 候选人阻挡归因 (Root Cause Analysis)
            </span>
            <span className="text-[11px] text-slate-400">具备资质但无法排班</span>
          </div>

          <div className="space-y-2 text-xs">
            {blockedCandidates.map((cand) => (
              <div
                key={cand.employeeId}
                className="p-2.5 rounded-xl bg-slate-50 border border-slate-200/70 space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="font-extrabold text-slate-800">
                    {cand.name}
                  </span>
                  <span className="text-[10px] font-bold text-rose-600 bg-rose-50 px-2 py-0.5 rounded-md border border-rose-200">
                    触发硬约束 {cand.violatedRule}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  {cand.reason}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer Action */}
      <div className="flex items-center justify-between pt-1 text-xs">
        <div className="text-slate-500 flex items-center gap-1 text-[11px]">
          <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
          <span>建议：可调整兼职可用时间，或通过 AI 推荐放宽连续工作限制后再次重排。</span>
        </div>
        <button
          type="button"
          onClick={onAskAiToResolve}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs shadow-sm transition"
        >
          <span>问问 AI 如何解决此冲突</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
