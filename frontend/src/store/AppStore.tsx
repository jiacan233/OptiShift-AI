import { createContext, useCallback, useContext, useMemo, useReducer, type ReactNode } from 'react'
import { api, apiErrorMessage, type EmployeePatch } from '@/api/client'
import type {
  ClarificationState,
  Conflict,
  Employee,
  FeasibleResult,
  PageId,
  RuleDefinition,
  Schedule,
  ScheduleChange,
  ScheduleOperationResult,
  ScheduleVersion,
  InfeasibleResult,
  ShiftType,
  Day,
} from '@/types'

interface WorkbenchState {
  page: PageId
  employees: Employee[]
  rules: RuleDefinition[]
  confirmedSchedule: Schedule | null
  draftSchedule: Schedule | null
  result: FeasibleResult | null
  conflicts: Conflict[]
  infeasibleResult: InfeasibleResult | null
  clarification: ClarificationState | null
  versions: ScheduleVersion[]
  selectedEmployeeId: string | null
  selectedShift: { day: Day; shift: ShiftType } | null
  isBootstrapping: boolean
  isRunning: boolean
  isSavingEmployee: string | null
  error: { code: string; message: string } | null
  notice: string | null
}

const initialState: WorkbenchState = {
  page: 'schedule',
  employees: [],
  rules: [],
  confirmedSchedule: null,
  draftSchedule: null,
  result: null,
  conflicts: [],
  infeasibleResult: null,
  clarification: null,
  versions: [],
  selectedEmployeeId: null,
  selectedShift: null,
  isBootstrapping: true,
  isRunning: false,
  isSavingEmployee: null,
  error: null,
  notice: null,
}

type Action =
  | { type: 'PATCH'; patch: Partial<WorkbenchState> }
  | { type: 'PAGE'; page: PageId }
  | { type: 'OPERATION_RESULT'; result: ScheduleOperationResult }
  | { type: 'EMPLOYEE_UPDATED'; employee: Employee }

function reducer(state: WorkbenchState, action: Action): WorkbenchState {
  if (action.type === 'PATCH') return { ...state, ...action.patch }
  if (action.type === 'PAGE') return { ...state, page: action.page }
  if (action.type === 'EMPLOYEE_UPDATED') {
    return {
      ...state,
      employees: state.employees.map((employee) => employee.id === action.employee.id ? action.employee : employee),
      isSavingEmployee: null,
      notice: `${action.employee.id} 的排班资料已更新。`,
    }
  }
  if (action.result.status === 'clarification_required') {
    return { ...state, clarification: action.result.clarification, conflicts: [], infeasibleResult: null, isRunning: false }
  }
  if (action.result.status === 'infeasible') {
    return {
      ...state,
      conflicts: action.result.conflicts,
      infeasibleResult: action.result,
      clarification: null,
      draftSchedule: null,
      result: null,
      isRunning: false,
    }
  }
  if (action.result.status === 'entity_not_found' || action.result.status === 'solver_unknown') {
    return {
      ...state,
      isRunning: false,
      clarification: null,
      error: { code: action.result.status, message: action.result.message },
    }
  }
  const schedule = action.result.schedule
  const isConfirmed = schedule.status === 'confirmed' || action.result.schedule_status === 'confirmed'
  return {
    ...state,
    result: action.result,
    conflicts: [],
    infeasibleResult: null,
    clarification: null,
    confirmedSchedule: isConfirmed ? schedule : state.confirmedSchedule,
    draftSchedule: isConfirmed ? null : schedule,
    isRunning: false,
  }
}

interface StoreValue extends WorkbenchState {
  activeSchedule: Schedule | null
  setPage(page: PageId): void
  bootstrap(): Promise<void>
  generate(prompt: string, weekStart: string): Promise<void>
  replan(prompt: string, changes: ScheduleChange[]): Promise<void>
  confirmDraft(): Promise<void>
  cancelDraft(): Promise<void>
  resolveClarification(employeeId: string): Promise<void>
  updateEmployee(employeeId: string, patch: EmployeePatch): Promise<void>
  selectShift(shift: { day: Day; shift: ShiftType } | null): void
  selectEmployee(employeeId: string | null): void
  dismissError(): void
  dismissNotice(): void
  dismissClarification(): void
}

const AppStore = createContext<StoreValue | null>(null)

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const run = useCallback(async (operation: () => Promise<ScheduleOperationResult>) => {
    dispatch({ type: 'PATCH', patch: { isRunning: true, error: null, notice: null } })
    try {
      const result = await operation()
      dispatch({ type: 'OPERATION_RESULT', result })
      if (result.status === 'feasible' || result.status === 'confirmed') {
        try {
          const versions = await api.schedules.versions(result.schedule_id)
          dispatch({ type: 'PATCH', patch: { versions } })
        } catch {
          // The result remains usable if optional history loading fails.
        }
      }
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
    }
  }, [])

  const bootstrap = useCallback(async () => {
    dispatch({ type: 'PATCH', patch: { isBootstrapping: true, error: null } })
    const [employeesResult, rulesResult, scheduleResult] = await Promise.allSettled([
      api.employees.list(),
      api.rules.list(),
      api.schedules.latest('confirmed'),
    ])
    const patch: Partial<WorkbenchState> = { isBootstrapping: false }
    if (employeesResult.status === 'fulfilled') patch.employees = employeesResult.value
    if (rulesResult.status === 'fulfilled') patch.rules = rulesResult.value
    if (scheduleResult.status === 'fulfilled' && scheduleResult.value) {
      patch.confirmedSchedule = scheduleResult.value
      try {
        const [versions, validated] = await Promise.all([
          api.schedules.versions(scheduleResult.value.schedule_id),
          api.schedules.validate(scheduleResult.value.schedule_id, scheduleResult.value.version),
        ])
        patch.versions = versions
        patch.result = validated
      } catch {
        patch.versions = []
      }
    }
    if (employeesResult.status === 'rejected' && rulesResult.status === 'rejected') {
      patch.error = apiErrorMessage(employeesResult.reason)
    }
    dispatch({ type: 'PATCH', patch })
  }, [])

  const generate = useCallback((prompt: string, weekStart: string) => (
    run(() => api.schedules.generate({ prompt, week_start: weekStart }))
  ), [run])

  const replan = useCallback(async (prompt: string, changes: ScheduleChange[]) => {
    const base = state.confirmedSchedule
    if (!base) {
      dispatch({
        type: 'PATCH',
        patch: { error: { code: 'base_schedule_required', message: '请先生成并确认一份排班，再执行临时调整。' } },
      })
      return
    }
    await run(() => api.schedules.replan({
      base_schedule_id: base.schedule_id,
      base_version: base.version,
      changes,
      minimize_changes: true,
      prompt,
    }))
  }, [run, state.confirmedSchedule])

  const confirmDraft = useCallback(async () => {
    const draft = state.draftSchedule
    if (!draft) return
    dispatch({ type: 'PATCH', patch: { isRunning: true, error: null } })
    try {
      const result = await api.schedules.confirm(draft.schedule_id, draft.version)
      dispatch({ type: 'OPERATION_RESULT', result })
      if (result.status === 'feasible' || result.status === 'confirmed') {
        const versions = await api.schedules.versions(result.schedule_id).catch(() => state.versions)
        dispatch({ type: 'PATCH', patch: { versions, notice: `排班 v${result.version} 已确认并生效。` } })
      }
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
    }
  }, [state.draftSchedule, state.versions])

  const cancelDraft = useCallback(async () => {
    const draft = state.draftSchedule
    if (!draft) return
    dispatch({ type: 'PATCH', patch: { isRunning: true, error: null } })
    try {
      await api.schedules.cancel(draft.schedule_id, draft.version)
      dispatch({ type: 'PATCH', patch: {
        draftSchedule: null,
        result: null,
        isRunning: false,
        notice: '草稿已取消，正式排班保持不变。',
      } })
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
    }
  }, [state.draftSchedule])

  const resolveClarification = useCallback(async (employeeId: string) => {
    if (!state.clarification) return
    await run(() => api.schedules.resolveClarification(state.clarification!.id, employeeId))
  }, [run, state.clarification])

  const updateEmployee = useCallback(async (employeeId: string, patch: EmployeePatch) => {
    dispatch({ type: 'PATCH', patch: { isSavingEmployee: employeeId, error: null, notice: null } })
    try {
      const employee = await api.employees.update(employeeId, patch)
      dispatch({ type: 'EMPLOYEE_UPDATED', employee })
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isSavingEmployee: null, error: apiErrorMessage(error) } })
    }
  }, [])

  const value = useMemo<StoreValue>(() => ({
    ...state,
    activeSchedule: state.draftSchedule ?? state.confirmedSchedule,
    setPage: (page) => dispatch({ type: 'PAGE', page }),
    bootstrap,
    generate,
    replan,
    confirmDraft,
    cancelDraft,
    resolveClarification,
    updateEmployee,
    selectShift: (selectedShift) => dispatch({ type: 'PATCH', patch: { selectedShift } }),
    selectEmployee: (selectedEmployeeId) => dispatch({ type: 'PATCH', patch: { selectedEmployeeId } }),
    dismissError: () => dispatch({ type: 'PATCH', patch: { error: null } }),
    dismissNotice: () => dispatch({ type: 'PATCH', patch: { notice: null } }),
    dismissClarification: () => dispatch({ type: 'PATCH', patch: { clarification: null } }),
  }), [state, bootstrap, generate, replan, confirmDraft, cancelDraft, resolveClarification, updateEmployee])

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>
}

export function useAppStore() {
  const value = useContext(AppStore)
  if (!value) throw new Error('useAppStore must be used within AppStoreProvider')
  return value
}
