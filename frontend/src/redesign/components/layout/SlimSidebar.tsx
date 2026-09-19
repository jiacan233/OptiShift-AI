import React from 'react'
import {
  Calendar,
  Users2,
  ShieldCheck,
  Bot,
  Users,
} from 'lucide-react'

interface SlimSidebarProps {
  activeTab: string
  setActiveTab: (tab: string) => void
  onOpenMobilePreview: () => void
  onOpenCopilot: () => void
  isCopilotOpen: boolean
}

export const SlimSidebar: React.FC<SlimSidebarProps> = ({
  activeTab,
  setActiveTab,
  onOpenMobilePreview,
  onOpenCopilot,
  isCopilotOpen,
}) => {
  const navItems = [
    { id: 'schedule', icon: Calendar, label: '排班工作台' },
    { id: 'employees', icon: Users2, label: '员工管理' },
    { id: 'rules', icon: ShieldCheck, label: '规则中心' },
  ]

  return (
    <aside className="fixed inset-y-0 left-0 z-30 w-16 md:w-20 bg-white border-r border-slate-200/70 flex flex-col items-center py-5 justify-between shrink-0 shadow-sm select-none">
      {/* Top Logo */}
      <div className="flex flex-col items-center gap-7">
        <button
          type="button"
          onClick={() => setActiveTab('schedule')}
          className="w-11 h-11 rounded-2xl bg-blue-600 text-white flex items-center justify-center shadow-lg shadow-blue-500/25 hover:bg-blue-700 transition active:scale-95"
          title="OptiShift 智能排班"
          aria-label="OptiShift 首页"
        >
          <Users className="w-5 h-5" />
        </button>

        {/* Navigation Items */}
        <nav className="flex flex-col items-center gap-3" aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = activeTab === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveTab(item.id)}
                className={`relative w-11 h-11 rounded-2xl flex items-center justify-center transition-all ${
                  isActive
                    ? 'text-blue-600 bg-blue-50/90 shadow-sm'
                    : 'text-slate-400 hover:text-slate-700 hover:bg-slate-50'
                }`}
                title={item.label}
                aria-label={item.label}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon className="w-5 h-5 stroke-[2]" />
                {isActive && (
                  <span className="absolute -left-3 md:-left-4.5 w-1 h-5 bg-blue-600 rounded-r-full" />
                )}
              </button>
            )
          })}

          {/* AI Copilot trigger button in sidebar */}
          <button
            type="button"
            onClick={onOpenCopilot}
            className={`relative w-11 h-11 rounded-2xl flex items-center justify-center transition-all ${
              isCopilotOpen
                ? 'text-indigo-600 bg-indigo-50 shadow-sm ring-1 ring-indigo-200'
                : 'text-slate-400 hover:text-indigo-600 hover:bg-indigo-50/50'
            }`}
            title="问问 AI (Copilot)"
            aria-label="打开 AI 助手"
          >
            <Bot className="w-5 h-5 stroke-[2]" />
            <span className="absolute top-2 right-2 w-2 h-2 bg-indigo-600 rounded-full animate-ping" />
          </button>
        </nav>
      </div>

      {/* Bottom Profile Avatar & Mobile Preview trigger */}
      <div className="flex flex-col items-center gap-4">
        <button
          type="button"
          onClick={onOpenMobilePreview}
          className="w-9 h-9 rounded-xl bg-slate-100 text-slate-500 flex items-center justify-center hover:bg-blue-50 hover:text-blue-600 transition text-xs font-semibold"
          title="切换手机伴生视图"
          aria-label="手机排班预览"
        >
          📱
        </button>
        <div className="relative group cursor-pointer" title="OptiShift 门店排班">
          <div className="w-10 h-10 rounded-full bg-blue-50 border-2 border-blue-200 flex items-center justify-center text-xs font-bold text-blue-700">
            OP
          </div>
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 bg-emerald-500 border-2 border-white rounded-full" />
        </div>
      </div>
    </aside>
  )
}
