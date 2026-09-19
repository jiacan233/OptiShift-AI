import React from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Smartphone,
  Bot,
} from 'lucide-react'

interface TopHeaderProps {
  currentWeekText: string
  onPrevWeek: () => void
  onNextWeek: () => void
  onAddShift: () => void
  onToggleMobilePreview: () => void
  showMobilePreview: boolean
  addShiftDisabled: boolean
  onOpenCopilot: () => void
  activeTabTitle?: string
  subTitle?: React.ReactNode
  weekSelector?: React.ReactNode
}

export const TopHeader: React.FC<TopHeaderProps> = ({
  currentWeekText,
  onPrevWeek,
  onNextWeek,
  onAddShift,
  onToggleMobilePreview,
  showMobilePreview,
  addShiftDisabled,
  onOpenCopilot,
  activeTabTitle = '排班工作台',
  subTitle,
  weekSelector,
}) => {

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-200/60">
      {/* Left: Title & Concise Global Solver Status */}
      <div className="flex items-center gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl md:text-2xl font-bold text-slate-900 tracking-tight">
              {activeTabTitle}
            </h1>

          </div>
          {subTitle && (
            <div className="mt-0.5 text-xs font-semibold text-slate-400">
              {subTitle}
            </div>
          )}
        </div>
      </div>

      {/* Middle: Week Date Picker */}
      {weekSelector ? (
        weekSelector
      ) : (
        <div className="flex items-center gap-1.5 bg-white border border-slate-200/80 rounded-2xl px-2 py-1 shadow-xs">
          <button
            type="button"
            onClick={onPrevWeek}
            className="w-7 h-7 rounded-xl flex items-center justify-center text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition"
            aria-label="上一周"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="px-2.5 text-xs md:text-sm font-semibold text-slate-800 tracking-tight select-none">
            {currentWeekText}
          </span>
          <button
            type="button"
            onClick={onNextWeek}
            className="w-7 h-7 rounded-xl flex items-center justify-center text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition"
            aria-label="下一周"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Right: Actions with Clear Visual Hierarchy */}
      <div className="flex items-center gap-2">
        {/* Secondary: Mobile Preview */}
        <button
          type="button"
          onClick={onToggleMobilePreview}
          className={`flex items-center gap-1.5 border rounded-xl px-2.5 py-1.5 text-xs font-semibold shadow-xs transition ${
            showMobilePreview
              ? 'bg-blue-50 border-blue-200 text-blue-700'
              : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
          }`}
          title="切换手机伴生视图"
          aria-label="顶部手机排班预览"
        >
          <Smartphone className="w-3.5 h-3.5 text-blue-500" />
          <span className="hidden xl:inline">手机端</span>
        </button>

        {/* Primary Action 1: 问问 AI (Copilot) */}
        <button
          type="button"
          onClick={onOpenCopilot}
          aria-label="问问 AI"
          className="flex items-center gap-1.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-xl px-3.5 py-1.5 text-xs font-bold shadow-sm shadow-blue-500/20 active:scale-[0.98] transition"
        >
          <Bot className="w-3.5 h-3.5" />
          <span>问问 AI</span>
        </button>

        {/* Primary Action 2: 新增班次 */}
        <button
          type="button"
          disabled={addShiftDisabled}
          onClick={onAddShift}
          aria-label="新增班次"
          className="flex items-center gap-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-800 rounded-xl px-3 py-1.5 text-xs font-bold shadow-xs active:scale-[0.98] transition"
        >
          <Plus className="w-3.5 h-3.5 text-blue-600" />
          <span className="hidden sm:inline">新增班次</span>
        </button>


      </div>
    </header>
  )
}
