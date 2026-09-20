import { createContext, useCallback, useContext, useMemo, useReducer, useRef, type ReactNode } from 'react'
import { api, apiErrorMessage, type RuleConfig, type EmployeePatch } from '@/api/client'
import { buildWeekWindow, currentMonday } from '@/lib/isoWeek'
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
  ScheduleWeekSummary,
  InfeasibleResult,
  ShiftType,
  Day,
} from '@/types'

interface WorkbenchState {
  page: PageId
  employees: Employee[]
  rules: RuleDefinition[]
  ruleConfig: RuleConfig
  activeWeekStart: string
  weekOptions: ScheduleWeekSummary[]
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
  isLoadingWeek: boolean
  isSavingEmployee: string | null
  error: { code: string; message: string } | null
  notice: string | null
}

const initialState: WorkbenchState = {
  page: 'schedule',
  employees: [],
  rules: [],
  ruleConfig: { manager_per_shift: 1, beverage_per_shift: 2, cashier_per_shift: 1, weekday_min_staff: 4, weekend_min_staff: 6, max_shifts_per_week: 5, max_consecutive_days: 5 },
  activeWeekStart: currentMonday(),
  weekOptions: [],
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
  isLoadingWeek: false,
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
  if (action.result.status === 'infeasible' || action.result.status === 'scenario_preview') {
    return {
      ...state,
      conflicts: action.result.conflicts,
      infeasibleResult: action.result.status === 'scenario_preview' && !action.result.scenario_patches?.length ? null : action.result,
      clarification: null,
      draftSchedule: state.draftSchedule,
      result: state.result,
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
  if (!('schedule' in action.result) || !action.result.schedule) {
    return { ...state, isRunning: false }
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
  setActiveWeek(weekStart: string): Promise<void>
  applyScheduleResult(result: ScheduleOperationResult): Promise<void>
  generate(prompt: string, weekStart: string, changes?: ScheduleChange[], weekendMinStaff?: number, maxConsecutiveDays?: number): Promise<boolean>
  replan(prompt: string, changes: ScheduleChange[]): Promise<boolean>
  confirmDraft(): Promise<void>
  cancelDraft(): Promise<void>
  resolveClarification(employeeId: string): Promise<void>
  updateEmployee(employeeId: string, patch: EmployeePatch): Promise<void>
  selectShift(shift: { day: Day; shift: ShiftType } | null): void
  selectEmployee(employeeId: string | null): void
  dismissInfeasibleResult(): void
  dismissError(): void
  dismissNotice(): void
  dismissClarification(): void
}

const AppStore = createContext<StoreValue | null>(null)

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const weekLoadRequestRef = useRef(0)
  const weekOptionsRequestRef = useRef(0)

  const refreshWeekOptions = useCallback(async (anchorWeekStart: string) => {
    const requestId = weekOptionsRequestRef.current + 1
    weekOptionsRequestRef.current = requestId
    try {
      const weeks = await api.schedules.weeks(anchorWeekStart)
      if (requestId === weekOptionsRequestRef.current) {
        dispatch({ type: 'PATCH', patch: { weekOptions: weeks.length ? weeks : buildWeekWindow(anchorWeekStart).map((week_start) => ({ week_start })) } })
      }
    } catch {
      if (requestId === weekOptionsRequestRef.current) {
        dispatch({ type: 'PATCH', patch: { weekOptions: buildWeekWindow(anchorWeekStart).map((week_start) => ({ week_start })) } })
      }
    }
  }, [])

  const loadWeek = useCallback(async (weekStart: string, preferredResult?: ScheduleOperationResult) => {
    const requestId = weekLoadRequestRef.current + 1
    weekLoadRequestRef.current = requestId
    dispatch({ type: 'PATCH', patch: {
      activeWeekStart: weekStart,
      isLoadingWeek: true,
      selectedShift: null,
      confirmedSchedule: null,
      draftSchedule: null,
      result: null,
      versions: [],
      conflicts: [],
      infeasibleResult: null,
      clarification: null,
      error: null,
    } })
    try {
      const context = await api.schedules.weekContext(weekStart)
      const display = context.display_schedule ?? context.draft_schedule ?? context.confirmed_schedule
      const preferredMatchesDisplay = (
        (preferredResult?.status === 'feasible' || preferredResult?.status === 'confirmed')
        && display !== null
        && preferredResult.schedule_id === display.schedule_id
        && preferredResult.version === display.version
        && preferredResult.schedule_status === display.status
      )
      let result = preferredMatchesDisplay ? preferredResult : context.result ?? null
      if (display) {
        result = await api.schedules.validate(display.schedule_id, display.version)
      }
      if (requestId !== weekLoadRequestRef.current) return
      dispatch({ type: 'PATCH', patch: {
        activeWeekStart: context.week_start || weekStart,
        confirmedSchedule: context.confirmed_schedule,
        draftSchedule: context.draft_schedule,
        result,
        versions: context.versions ?? [],
        conflicts: [],
        infeasibleResult: null,
        clarification: null,
        isLoadingWeek: false,
        isRunning: false,
      } })
    } catch (error) {
      if (requestId !== weekLoadRequestRef.current) return
      dispatch({ type: 'PATCH', patch: {
        confirmedSchedule: null,
        draftSchedule: null,
        result: null,
        versions: [],
        conflicts: [],
        infeasibleResult: null,
        isLoadingWeek: false,
        isRunning: false,
        error: apiErrorMessage(error),
      } })
    }
    if (requestId === weekLoadRequestRef.current) await refreshWeekOptions(weekStart)
  }, [refreshWeekOptions])

  const applyScheduleResult = useCallback(async (result: ScheduleOperationResult) => {
    if (result.status === 'feasible' || result.status === 'confirmed') {
      await loadWeek(result.schedule.week_start, result)
      return
    }
    dispatch({ type: 'OPERATION_RESULT', result })
  }, [loadWeek])

  const run = useCallback(async (operation: () => Promise<ScheduleOperationResult>) => {
    dispatch({ type: 'PATCH', patch: { isRunning: true, error: null, notice: null } })
    try {
      const result = await operation()
      await applyScheduleResult(result)
      return result.status === 'feasible' || result.status === 'confirmed'
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
      return false
    }
  }, [applyScheduleResult])

  const bootstrap = useCallback(async () => {
    dispatch({ type: 'PATCH', patch: { isBootstrapping: true, error: null } })
    const [employeesResult, rulesResult, draftResult, confirmedResult] = await Promise.allSettled([
      api.employees.list(),
      api.rules.configuration(),
      api.schedules.latest('draft'),
      api.schedules.latest('confirmed'),
    ])
    const patch: Partial<WorkbenchState> = {}
    if (employeesResult.status === 'fulfilled') patch.employees = employeesResult.value
    if (rulesResult.status === 'fulfilled') { patch.rules = rulesResult.value.rules; patch.ruleConfig = rulesResult.value.config }
    const bootstrapError = employeesResult.status === 'rejected'
      ? apiErrorMessage(employeesResult.reason)
      : rulesResult.status === 'rejected'
        ? apiErrorMessage(rulesResult.reason)
        : null
    dispatch({ type: 'PATCH', patch })

    const pendingDraft = draftResult.status === 'fulfilled' ? draftResult.value : null
    const latestConfirmed = confirmedResult.status === 'fulfilled' ? confirmedResult.value : null
    const initialWeekStart = pendingDraft?.week_start ?? latestConfirmed?.week_start ?? currentMonday()
    await loadWeek(initialWeekStart)
    dispatch({ type: 'PATCH', patch: {
      isBootstrapping: false,
      ...(bootstrapError ? { error: bootstrapError } : {}),
    } })
  }, [loadWeek])

  const setActiveWeek = useCallback(async (weekStart: string) => {
    await loadWeek(weekStart)
  }, [loadWeek])

  const generate = useCallback((prompt: string, weekStart: string, changes: ScheduleChange[] = [], weekendMinStaff?: number, maxConsecutiveDays?: number) => (
    run(() => api.schedules.generate({ prompt, week_start: weekStart, changes, weekend_min_staff: weekendMinStaff, max_consecutive_days: maxConsecutiveDays }))
  ), [run])

  const replan = useCallback(async (prompt: string, changes: ScheduleChange[]) => {
    const base = state.confirmedSchedule
    if (!base) {
      dispatch({
        type: 'PATCH',
        patch: { error: { code: 'base_schedule_required', message: '请先生成并确认一份排班，再执行临时调整。' } },
      })
      return false
    }
    return run(() => api.schedules.replan({
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
      await applyScheduleResult(result)
      dispatch({ type: 'PATCH', patch: { notice: `排班 v${result.status === 'confirmed' || result.status === 'feasible' ? result.version : draft.version} 已确认并生效。` } })
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
    }
  }, [applyScheduleResult, state.draftSchedule])

  const cancelDraft = useCallback(async () => {
    const draft = state.draftSchedule
    if (!draft) return
    dispatch({ type: 'PATCH', patch: { isRunning: true, error: null } })
    try {
      await api.schedules.cancel(draft.schedule_id, draft.version)
      await loadWeek(state.activeWeekStart)
      dispatch({ type: 'PATCH', patch: { notice: '草稿已取消，正式排班保持不变。' } })
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isRunning: false, error: apiErrorMessage(error) } })
    }
  }, [loadWeek, state.activeWeekStart, state.draftSchedule])

  const resolveClarification = useCallback(async (employeeId: string) => {
    if (!state.clarification) return
    await run(() => api.schedules.resolveClarification(state.clarification!.id, employeeId))
  }, [run, state.clarification])

  const updateEmployee = useCallback(async (employeeId: string, patch: EmployeePatch) => {
    dispatch({ type: 'PATCH', patch: { isSavingEmployee: employeeId, error: null, notice: null } })
    try {
      const employee = await api.employees.update(employeeId, patch)
      dispatch({ type: 'EMPLOYEE_UPDATED', employee })
      await loadWeek(state.activeWeekStart)
    } catch (error) {
      dispatch({ type: 'PATCH', patch: { isSavingEmployee: null, error: apiErrorMessage(error) } })
    }
  }, [loadWeek, state.activeWeekStart])

  const value = useMemo<StoreValue>(() => ({
    ...state,
    activeSchedule: state.draftSchedule ?? state.confirmedSchedule,
    setPage: (page) => dispatch({ type: 'PAGE', page }),
    bootstrap,
    setActiveWeek,
    applyScheduleResult,
    generate,
    replan,
    confirmDraft,
    cancelDraft,
    resolveClarification,
    updateEmployee,
    selectShift: (selectedShift) => dispatch({ type: 'PATCH', patch: { selectedShift } }),
    selectEmployee: (selectedEmployeeId) => dispatch({ type: 'PATCH', patch: { selectedEmployeeId } }),
    dismissInfeasibleResult: () => dispatch({ type: 'PATCH', patch: { infeasibleResult: null, conflicts: [] } }),
    dismissError: () => dispatch({ type: 'PATCH', patch: { error: null } }),
    dismissNotice: () => dispatch({ type: 'PATCH', patch: { notice: null } }),
    dismissClarification: () => dispatch({ type: 'PATCH', patch: { clarification: null } }),
  }), [state, bootstrap, setActiveWeek, applyScheduleResult, generate, replan, confirmDraft, cancelDraft, resolveClarification, updateEmployee])

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>
}

export function useAppStore() {
  const value = useContext(AppStore)
  if (!value) throw new Error('useAppStore must be used within AppStoreProvider')
  return value
}
