import { useState, type ReactNode } from 'react'
import type { PageId } from '@/types'
import { SlimSidebar } from '@/redesign/components/layout/SlimSidebar'
import { MobileSchedule } from '@/redesign/MobileSchedule'

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
  const [mobile, setMobile] = useState(false)

  return (
    <div
      className={`min-h-screen bg-[#F4F7FC] pl-16 md:pl-20 transition-[padding] duration-200 ${
        agentOpen ? 'lg:pr-[380px] xl:pr-[440px]' : ''
      }`}
    >
      <SlimSidebar
        activeTab={page}
        setActiveTab={(tab) => onPageChange(tab as PageId)}
        onOpenMobilePreview={() => setMobile(true)}
        onOpenCopilot={onOpenAgent}
        isCopilotOpen={agentOpen}
      />
      <main className="mx-auto max-w-[1680px] p-3 sm:p-5 lg:p-6 min-w-0">
        {page === 'schedule' ? children : (
          <div className="rounded-[36px] border border-slate-200/70 bg-white p-5 shadow-soft md:p-7">
            <header className="mb-5 flex items-center justify-between gap-3">
              <h1 className="text-xl font-bold text-slate-900">{page === 'employees' ? '员工管理' : '规则中心'}</h1>
              <button className="btn-primary" onClick={onOpenAgent}>问问 AI</button>
            </header>
            {children}
          </div>
        )}
      </main>
      {mobile && <MobileSchedule onClose={() => setMobile(false)} />}
    </div>
  )
}
