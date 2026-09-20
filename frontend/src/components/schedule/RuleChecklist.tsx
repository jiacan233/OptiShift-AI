import { AlertTriangle, Check, ShieldCheck, X } from 'lucide-react'
import { ruleCheckMessage, rulePresentation } from '@/lib/presentation'
import type { ValidationResult } from '@/types'

export function RuleChecklist({ validation }: { validation: ValidationResult | null }) {
  if (!validation) {
    return (
      <div className="panel p-5">
        <div className="mb-5 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-400"><ShieldCheck className="h-5 w-5" /></span>
          <div><p className="text-sm font-extrabold text-ink">硬约束检查</p><p className="text-[11px] text-slate-400">等待后端规则校验结果</p></div>
        </div>
        <div className="space-y-2">
          {['H01', 'R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09'].map((rule) => (
            <div key={rule} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
              <span className="h-4 w-4 rounded-full border border-slate-300" /> <strong>{rule}</strong> {rulePresentation(rule).name}
            </div>
          ))}
        </div>
      </div>
    )
  }

  const authorized = validation.checks.filter((check) => check.classification === 'VIOLATED_AUTHORIZED').length
  const stale = validation.freshness_valid === false
  const blocked = stale || validation.confirmable === false
  const passed = validation.passed && !blocked
  const hasAcceptedExceptions = blocked || validation.compliance_status === 'authorized_violations'
  const tone = passed ? 'text-emerald-700' : hasAcceptedExceptions ? 'text-amber-700' : 'text-red-700'
  const summary = blocked
    ? stale ? '草稿已过期 · 请重新生成' : '草稿不可确认 · 请检查规则或重新生成'
    : authorized ? `${validation.passed_count} 项满足 · ${authorized} 项已授权例外` : `${validation.passed_count} / ${validation.total} ${passed ? '全部通过' : '存在冲突'}`
  return (
    <div className="panel overflow-hidden">
      <div className={`p-5 ${passed ? 'bg-emerald-50/70' : hasAcceptedExceptions ? 'bg-amber-50/70' : 'bg-red-50/70'}`}>
        <div className="flex items-center gap-3">
          <span className={`grid h-10 w-10 place-items-center rounded-xl ${passed ? 'bg-emerald-100 text-emerald-700' : hasAcceptedExceptions ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'}`}>
            {passed ? <ShieldCheck className="h-5 w-5" /> : <AlertTriangle className="h-5 w-5" />}
          </span>
          <div>
            <p className="text-sm font-extrabold text-ink">硬约束检查</p>
            <p className={`text-[11px] font-bold ${tone}`}>
              {summary}
            </p>
          </div>
        </div>
      </div>
      {blocked && <p role="status" className="px-5 py-3 text-xs text-amber-800">{validation.conflict?.message ?? '规则检查结果不能代表草稿仍可确认，请取消后重新生成。'}</p>}
      <div className="max-h-[490px] space-y-1 overflow-y-auto p-3 soft-scrollbar">
        {validation.checks.map((check) => (
          <div key={check.rule_id} title={ruleCheckMessage(check.rule_id, check.passed, check.message)} className="flex items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-slate-50">
            <span className={`grid h-5 w-5 place-items-center rounded-full ${check.passed ? 'bg-emerald-100 text-emerald-700' : check.classification === 'VIOLATED_AUTHORIZED' ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'}`}>
              {check.passed ? <Check className="h-3 w-3" /> : check.classification === 'VIOLATED_AUTHORIZED' ? <AlertTriangle className="h-3 w-3" /> : <X className="h-3 w-3" />}
            </span>
            <span className="w-8 text-xs font-extrabold text-slate-700">{check.rule_id}</span>
            <span className="min-w-0 flex-1 truncate text-[11px] text-slate-500">{check.classification === 'VIOLATED_AUTHORIZED' ? `${rulePresentation(check.rule_id).name} · 已授权例外` : ruleCheckMessage(check.rule_id, check.passed, check.message)}</span>
          </div>
        ))}
      </div>
      <div className={`border-t px-5 py-4 text-center ${passed ? 'border-emerald-100 bg-emerald-50' : hasAcceptedExceptions ? 'border-amber-100 bg-amber-50' : 'border-red-100 bg-red-50'}`}>
        <p className={`text-sm font-black tracking-tight ${tone}`}>
          {summary}
        </p>
      </div>
    </div>
  )
}
