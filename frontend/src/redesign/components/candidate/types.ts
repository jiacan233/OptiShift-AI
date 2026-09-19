import type { FeasibleResult, Schedule, ScheduleVersion } from '@/types'

// Presentation contract only. Candidate promotion must be supplied by a real API adapter.
export interface CandidatePlan {
  id: string
  kind: 'current' | 'draft' | 'candidate'
  name: string
  tag: string
  subtitle: string
  schedule: Schedule
  result: FeasibleResult | null
  version?: ScheduleVersion
}
