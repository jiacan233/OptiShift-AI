import { useState, type ReactNode } from 'react'
import {
  CalendarRange,
  ChevronRight,
  Menu,
  MessageCircleMore,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from 'lucide-react'
import type { PageId } from '@/types'

const pages: Array<{ id: PageId; label: string; detail: string; icon: typeof CalendarRange }> = [
  { id: 'schedule', label: '排班工作台', detail: '生成、重排与确认', icon: CalendarRange },
  { id: 'employees', label: '员工管理', detail: '可用时间与偏好', icon: Users },
  { id: 'rules', label: '规则中心', detail: '约束与优化目标', icon: ShieldCheck },
]

export function AppShell({
  page,
  onPageChange,
  children,
  agentOpen,
  onOpenAgent,
}: {
  page: PageId
  onPageChange(page: PageId): void
  children: ReactNode
  agentOpen: boolean
  onOpenAgent(): void
}) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const current = pages.find((item) => item.id === page)!

  const navigate = (next: PageId) => {
    onPageChange(next)
    setMobileOpen(false)
  }

  return (
    <div className={`min-h-screen bg-canvas transition-[padding] duration-200 lg:grid lg:grid-cols-[252px_minmax(0,1fr)] ${agentOpen ? 'lg:pr-[380px] xl:pr-[440px]' : ''}`}>
      {mobileOpen && (
        <button
          className="fixed inset-0 z-30 bg-ink/45 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-label="关闭导航"
        />
      )}

      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[268px] flex-col bg-ink text-white transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:w-auto ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <div className="flex h-20 items-center gap-3 border-b border-white/10 px-5">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-teal-500 text-white shadow-lg shadow-teal-950/20">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <p className="text-lg font-extrabold tracking-tight">OptiShift</p>
            <p className="text-[11px] font-semibold tracking-[0.14em] text-slate-400">智能排班助手</p>
          </div>
          <button className="ml-auto rounded-lg p-2 text-slate-300 hover:bg-white/10 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="关闭导航">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-2 px-3 py-6">
          <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">工作空间</p>
          {pages.map((item) => {
            const Icon = item.icon
            const active = item.id === page
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.id)}
                className={`group flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition ${active ? 'bg-white text-ink shadow-lg shadow-slate-950/20' : 'text-slate-300 hover:bg-white/8 hover:text-white'}`}
              >
                <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${active ? 'bg-teal-50 text-teal-700' : 'bg-white/8 text-slate-300'}`}>
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-bold">{item.label}</span>
                  <span className={`block truncate text-[11px] ${active ? 'text-slate-500' : 'text-slate-500'}`}>{item.detail}</span>
                </span>
                {active && <ChevronRight className="h-4 w-4 text-teal-600" />}
              </button>
            )
          })}
        </nav>

        <div className="m-4 rounded-2xl border border-white/10 bg-white/5 p-4">
          <div className="mb-3 flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-40" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
            </span>
            <p className="text-xs font-bold text-slate-200">确定性求解链路</p>
          </div>
          <p className="text-[11px] leading-5 text-slate-400">LLM 负责理解请求，约束求解器负责生成并验证排班。</p>
        </div>
      </aside>

      <main className="min-w-0">
        <header className="sticky top-0 z-20 flex h-16 items-center border-b border-slate-200/80 bg-canvas/90 px-4 backdrop-blur-xl sm:px-6 lg:h-20 lg:px-8">
          <button className="mr-3 rounded-xl border border-slate-200 bg-white p-2 text-slate-700 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="打开导航">
            <Menu className="h-5 w-5" />
          </button>
          <div>
            <p className="text-xs font-semibold text-slate-500">AI 智能排班助手</p>
            <h1 className="text-lg font-extrabold tracking-tight text-ink lg:text-xl">{current.label}</h1>
          </div>
          <div className="ml-auto hidden items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 xl:flex">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            后端统一数据源
          </div>
          <button type="button" onClick={onOpenAgent} className={`ml-auto inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-extrabold shadow-sm transition xl:ml-3 ${agentOpen ? 'bg-teal-50 text-teal-700 ring-1 ring-teal-200' : 'bg-teal-600 text-white hover:bg-teal-700'}`}>
            <MessageCircleMore className="h-4 w-4" />问问 AI
          </button>
        </header>
        <div className="mx-auto max-w-[1720px] p-4 sm:p-6 lg:p-8">{children}</div>
      </main>
    </div>
  )
}
