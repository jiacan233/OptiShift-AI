import { useState, type ReactNode } from 'react'
import { CalendarRange, Users, ShieldCheck, Bot, Sparkles, Smartphone } from 'lucide-react'
import type { PageId } from '@/types'
import { MobileSchedule } from '@/redesign/MobileSchedule'

const pages = [
  { id: 'schedule' as const, label: '排班工作台', detail: '让每个班次，都恰到好处。', icon: CalendarRange },
  { id: 'employees' as const, label: '员工管理', detail: '员工档案、认证技能与可用时间', icon: Users },
  { id: 'rules' as const, label: '规则中心', detail: '规则约束与排班试算', icon: ShieldCheck },
]

export function AppShell({ page, onPageChange, children, agentOpen, onOpenAgent }: {
  page: PageId; onPageChange(page: PageId): void; children: ReactNode; agentOpen: boolean; onOpenAgent(): void
}) {
  const [mobile, setMobile] = useState(false)
  const current = pages.find(item => item.id === page)!
  return <div className={`min-h-screen bg-[#F4F7FC] pl-14 transition-[padding] md:pl-20 ${agentOpen ? 'lg:pr-[380px] xl:pr-[440px]' : ''}`}>
    <aside className="fixed inset-y-0 left-0 z-30 flex w-14 flex-col items-center border-r border-slate-200/70 bg-white py-6 md:w-20">
      <button onClick={() => onPageChange('schedule')} aria-label="OptiShift 首页" className="mb-10 grid h-10 w-10 place-items-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-200"><Sparkles className="h-5 w-5" /></button>
      <nav className="flex flex-col gap-4" aria-label="主导航">{pages.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => onPageChange(id)} title={label} aria-label={label} aria-current={page === id ? 'page' : undefined} className={`grid h-10 w-10 place-items-center rounded-2xl transition ${page === id ? 'bg-blue-50 text-blue-600' : 'text-slate-400 hover:bg-slate-50 hover:text-slate-700'}`}><Icon className="h-5 w-5" /></button>)}
        <button aria-label="打开 AI 助手" title="AI 助手" onClick={onOpenAgent} className="grid h-10 w-10 place-items-center rounded-2xl text-indigo-500 hover:bg-indigo-50"><Bot className="h-5 w-5" /></button>
      </nav>
      <button className="mt-auto grid h-10 w-10 place-items-center rounded-xl text-slate-400 hover:bg-blue-50 hover:text-blue-600" title="手机排班预览" aria-label="手机排班预览" onClick={() => setMobile(true)}><Smartphone className="h-5 w-5" /></button>
    </aside>
    <main className="mx-auto max-w-[1680px] p-3 sm:p-6 lg:p-8">
      <header className="mb-6 flex flex-wrap items-center gap-4 px-1">
        <div className="min-w-0 flex-1"><p className="mb-1 text-[11px] font-bold tracking-[.18em] text-blue-600">OPTISHIFT / WORKSPACE</p><h1 className="text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">{current.label}</h1><p className="mt-1 text-xs text-slate-400">{current.detail}</p></div>
        <button onClick={onOpenAgent} className={`btn-primary ${agentOpen ? '!bg-indigo-600' : ''}`}><Sparkles className="h-4 w-4" />问问 AI</button>
      </header>
      <div className="min-w-0 rounded-[28px] border border-white bg-white p-3 shadow-[0_8px_40px_rgba(30,64,175,0.04)] sm:p-6 lg:rounded-[36px]">{children}</div>
    </main>
    {mobile && <MobileSchedule onClose={() => setMobile(false)} />}
  </div>
}
