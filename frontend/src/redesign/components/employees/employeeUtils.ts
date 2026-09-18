
export const getCleanName = (name: string): string => {
  return name.replace(/\s*\([^)]*\)$/, '').trim()
}

export const ROLE_ORDER: Record<string, number> = {
  店长: 1,
  副店长: 2,
  值班主管: 3,
  高级店员: 4,
  店员: 5,
  全职员工: 5,
  兼职: 6,
  兼职员工: 6,
}

export const ROLE_BADGE_STYLES: Record<string, string> = {
  店长: 'bg-blue-50 text-blue-700 border-blue-200/80',
  副店长: 'bg-indigo-50 text-indigo-700 border-indigo-200/80',
  值班主管: 'bg-purple-50 text-purple-700 border-purple-200/80',
  高级店员: 'bg-teal-50 text-teal-700 border-teal-200/80',
  店员: 'bg-slate-100 text-slate-700 border-slate-200/80',
  全职员工: 'bg-slate-100 text-slate-700 border-slate-200/80',
  兼职: 'bg-amber-50 text-amber-700 border-amber-200/80',
  兼职员工: 'bg-amber-50 text-amber-700 border-amber-200/80',
}

export const SKILL_BADGE_STYLES: Record<string, string> = {
  店长值守: 'bg-blue-50 text-blue-700 border-blue-200/80',
  饮品制作: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
  收银: 'bg-purple-50 text-purple-700 border-purple-200/80',
  库存管理: 'bg-amber-50 text-amber-700 border-amber-200/80',
}

export const DAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const DAYS_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
export const DAYS_CN_MAP: Record<string, string> = {
  Mon: '周一',
  Tue: '周二',
  Wed: '周三',
  Thu: '周四',
  Fri: '周五',
  Sat: '周六',
  Sun: '周日',
}
