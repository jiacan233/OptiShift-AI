import React from 'react'
import { AlertTriangle, ShieldAlert, UserX, X, HelpCircle, ArrowRight } from 'lucide-react'

export interface ConflictBannerProps {
  onClose: () => void
  onAskAiToResolve?: () => void
  coverageGaps?: {
    ruleId: string
    ruleName: string
    detail: string
    shortage: number
  }[]
  blockedCandidates?: {
    employeeId: string
    name: string
    reason: string
    violatedRule: string
  }[]
}

export const ConflictBanner: React.FC<ConflictBannerProps> = ({
  onClose,
  onAskAiToResolve,
  coverageGaps = [],
  blockedCandidates = [],
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
              {coverageGaps.length > 0 ? `缺少 ${coverageGaps.reduce((acc, g) => acc + g.shortage, 0)} 人` : '暂无'}
            </span>
          </div>

          {coverageGaps.length > 0 ? (
            <div className="space-y-2">
              {coverageGaps.map((gap, i) => (
                <div key={i} className="p-2.5 rounded-xl bg-rose-50/50 border border-rose-100/80 flex items-center justify-between">
                  <div>
                    <div className="text-xs font-extrabold text-slate-900">
                      {gap.ruleId} · {gap.ruleName}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {gap.detail}
                    </div>
                  </div>
                  <span className="text-xs font-bold text-rose-600 bg-white px-2 py-1 rounded-lg border border-rose-200">
                    缺口 -{gap.shortage}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 py-3 text-center">暂无覆盖缺口明细</p>
          )}
        </div>

        {/* Right: 候选人阻挡分析 */}
        <div className="bg-white rounded-2xl p-4 border border-rose-200/60 shadow-xs space-y-3">
          <div className="flex items-center justify-between text-xs font-bold text-slate-800 border-b border-slate-100 pb-2">
            <span className="flex items-center gap-1.5 text-amber-600">
              <UserX className="w-4 h-4" /> 候选人阻挡归因 (Root Cause Analysis)
            </span>
            <span className="text-[11px] text-slate-400">具备资质但无法排班</span>
          </div>

          {blockedCandidates.length > 0 ? (
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
          ) : (
            <p className="text-xs text-slate-400 py-3 text-center">暂无候选人阻挡明细</p>
          )}
        </div>
      </div>

      {/* Footer Action */}
      <div className="flex items-center justify-between pt-1 text-xs">
        <div className="text-slate-500 flex items-center gap-1 text-[11px]">
          <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
          <span>建议：可调整员工可用时间、请假安排或补充技能后再次重排。</span>
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
