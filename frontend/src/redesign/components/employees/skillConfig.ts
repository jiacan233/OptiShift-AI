import React from 'react'
import { ShieldCheck, Coffee, CreditCard, Package, Award } from 'lucide-react'
import { SkillType } from '../../types/schedule'

export interface SkillMeta {
  key: SkillType | string
  label: string
  shortLabel: string
  summaryLabel: string
  icon: React.ComponentType<{ className?: string }>
  iconColor: string
  textColor: string
  bgColor: string
  borderColor: string
  badgeStyle: string
}

export const SKILL_METAS: Record<string, SkillMeta> = {
  '店长值守': {
    key: '店长值守',
    label: '店长值守',
    shortLabel: '店长值守',
    summaryLabel: '店长资格',
    icon: ShieldCheck,
    iconColor: 'text-blue-600',
    textColor: 'text-blue-700',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200/80',
    badgeStyle: 'bg-blue-50/80 text-blue-700 border-blue-200/80 hover:bg-blue-100/70',
  },
  '饮品制作': {
    key: '饮品制作',
    label: '饮品制作',
    shortLabel: '饮品制作',
    summaryLabel: '饮品制作',
    icon: Coffee,
    iconColor: 'text-emerald-600',
    textColor: 'text-emerald-700',
    bgColor: 'bg-emerald-50',
    borderColor: 'border-emerald-200/80',
    badgeStyle: 'bg-emerald-50/80 text-emerald-700 border-emerald-200/80 hover:bg-emerald-100/70',
  },
  '收银': {
    key: '收银',
    label: '收银',
    shortLabel: '收银',
    summaryLabel: '收银配备',
    icon: CreditCard,
    iconColor: 'text-purple-600',
    textColor: 'text-purple-700',
    bgColor: 'bg-purple-50',
    borderColor: 'border-purple-200/80',
    badgeStyle: 'bg-purple-50/80 text-purple-700 border-purple-200/80 hover:bg-purple-100/70',
  },
  '库存管理': {
    key: '库存管理',
    label: '库存管理',
    shortLabel: '库存管理',
    summaryLabel: '库存管理',
    icon: Package,
    iconColor: 'text-amber-600',
    textColor: 'text-amber-700',
    bgColor: 'bg-amber-50',
    borderColor: 'border-amber-200/80',
    badgeStyle: 'bg-amber-50/80 text-amber-700 border-amber-200/80 hover:bg-amber-100/70',
  },
}

export const DEFAULT_SKILL_META: SkillMeta = {
  key: '通用技能',
  label: '通用技能',
  shortLabel: '通用技能',
  summaryLabel: '通用技能',
  icon: Award,
  iconColor: 'text-slate-500',
  textColor: 'text-slate-700',
  bgColor: 'bg-slate-50',
  borderColor: 'border-slate-200/80',
  badgeStyle: 'bg-slate-50 text-slate-700 border-slate-200/80 hover:bg-slate-100/70',
}

export const getSkillMeta = (skillName: string): SkillMeta => {
  return (
    SKILL_METAS[skillName] || {
      ...DEFAULT_SKILL_META,
      key: skillName,
      label: skillName,
      shortLabel: skillName,
      summaryLabel: skillName,
    }
  )
}

// Configurable constants for skill display threshold
export const DESKTOP_MAX_VISIBLE_SKILLS = 4
export const TABLET_MAX_VISIBLE_SKILLS = 3
export const MOBILE_MAX_VISIBLE_SKILLS = 2
