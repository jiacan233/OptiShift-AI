import { useEffect, useRef } from 'react'
import { AlertCircle, CheckCircle2, X } from 'lucide-react'
import { AppShell } from '@/components/AppShell'
import { AgentPanel } from '@/components/agent/AgentPanel'
import { EmployeeDetail } from '@/redesign/EmployeeDetail'
import { useAgentStore } from '@/store/AgentStore'
import { useAppStore } from '@/store/AppStore'
import { ScheduleWorkbench } from '@/pages/ScheduleWorkbench'
import { EmployeesPage } from '@/pages/EmployeesPage'
import { RulesPage } from '@/pages/RulesPage'
import { errorCodeLabel, problemMessage } from '@/lib/presentation'

export default function App() {
  const store = useAppStore()
  const agent = useAgentStore()
  const { bootstrap } = store
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    void bootstrap()
  }, [bootstrap])

  return (
    <>
    <AppShell page={store.page} onPageChange={store.setPage} agentOpen={agent.isChatOpen} onOpenAgent={agent.openChat}>
      {store.error && (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-red-900" role="alert">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold">{errorCodeLabel(store.error.code)}</p>
            <p className="mt-0.5 text-sm text-red-700">{problemMessage(store.error.code, store.error.message)}</p>
            <p className="mt-1 text-[10px] font-semibold tracking-wide text-red-500">错误类型：{errorCodeLabel(store.error.code)}</p>
          </div>
          <button onClick={store.dismissError} className="rounded-lg p-1 text-red-500 hover:bg-red-100" aria-label="关闭错误">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {store.notice && (
        <div className="mb-5 flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-900" role="status">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
          <p className="min-w-0 flex-1 text-sm font-medium">{store.notice}</p>
          <button onClick={store.dismissNotice} className="rounded-lg p-1 text-emerald-600 hover:bg-emerald-100" aria-label="关闭提示">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {store.page === 'schedule' && <ScheduleWorkbench />}
      {store.page === 'employees' && <EmployeesPage />}
      {store.page === 'rules' && <RulesPage />}
    </AppShell>
    <AgentPanel />
    <EmployeeDetail />
    </>
  )
}
