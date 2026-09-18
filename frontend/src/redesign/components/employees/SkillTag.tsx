import React from 'react'
import { SkillType } from '../../types/schedule'
import { getSkillMeta } from './skillConfig'

interface SkillTagProps {
  skill: SkillType | string
  showIcon?: boolean
  useShortLabel?: boolean
  className?: string
}

export const SkillTag: React.FC<SkillTagProps> = ({
  skill,
  showIcon = true,
  useShortLabel = true,
  className = '',
}) => {
  const meta = getSkillMeta(skill)
  const Icon = meta.icon
  const displayName = useShortLabel ? meta.shortLabel : meta.label

  return (
    <span
      className={`inline-flex items-center gap-1 text-[10.5px] font-bold px-1.5 py-0.5 rounded-md border transition-colors select-none ${meta.badgeStyle} ${className}`}
      title={`认证资质: ${meta.label}`}
    >
      {showIcon && <Icon className={`w-3 h-3 ${meta.iconColor} shrink-0`} />}
      <span className="leading-tight tracking-tight">{displayName}</span>
    </span>
  )
}
