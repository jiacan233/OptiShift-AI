import { ArrowRight } from 'lucide-react'
import type { AgentSuggestion } from '@/types'

export function SuggestionCard({ suggestion, disabled = false, onApply }: { suggestion: AgentSuggestion; disabled?: boolean; onApply(suggestion: AgentSuggestion): void }) {
  return (
    <article className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50/40 via-white to-purple-50/30 p-3">
      <p className="text-[10px] font-black uppercase tracking-[0.12em] text-blue-700">{suggestion.suggestion_id}</p>
      {suggestion.title && <h4 className="mt-1 text-sm font-extrabold text-slate-800">{suggestion.title}</h4>}
      <p className="mt-1 text-xs leading-5 text-slate-600">{suggestion.content ?? suggestion.description}</p>
      <button type="button" disabled={disabled} onClick={() => onApply(suggestion)} className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-blue-700 hover:text-blue-800 disabled:cursor-not-allowed disabled:opacity-45">
        请求生成草稿 <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </article>
  )
}
