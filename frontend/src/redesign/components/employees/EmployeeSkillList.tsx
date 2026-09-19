import React from 'react'
import { SkillType } from '../../types/schedule'
import { SkillTag } from './SkillTag'
import { getSkillMeta, DESKTOP_MAX_VISIBLE_SKILLS } from './skillConfig'

interface EmployeeSkillListProps {
  skills: SkillType[]
  maxVisible?: number
  className?: string
}

export const EmployeeSkillList: React.FC<EmployeeSkillListProps> = ({
  skills,
  maxVisible = DESKTOP_MAX_VISIBLE_SKILLS,
  className = '',
}) => {
  if (!skills || skills.length === 0) {
    return (
      <span className="text-[11px] text-slate-300 font-normal select-none">
        暂无认证
      </span>
    )
  }

  // Display strategy:
  // If skills.length <= maxVisible (e.g. <= 4), show all tags!
  // If skills.length > maxVisible, show (maxVisible - 1) tags + "+N" badge.
  const hasOverflow = skills.length > maxVisible
  const visibleSkills = hasOverflow ? skills.slice(0, maxVisible - 1) : skills
  const hiddenSkills = hasOverflow ? skills.slice(maxVisible - 1) : []

  return (
    <div className={`flex items-center gap-1.5 flex-wrap ${className}`}>
      {visibleSkills.map((skill) => (
        <SkillTag key={skill} skill={skill} />
      ))}

      {hasOverflow && (
        <div className="relative group/skillOverflow inline-flex items-center">
          <span
            className="inline-flex items-center text-[10px] font-extrabold px-1.5 py-0.5 rounded-md bg-slate-100/90 text-slate-600 border border-slate-200/90 hover:bg-slate-200/90 hover:text-slate-800 transition cursor-help select-none shadow-2xs"
            title={`全部折叠技能: ${hiddenSkills.map((s) => getSkillMeta(s).label).join('、')}`}
          >
            +{hiddenSkills.length}
          </span>

          {/* Floating Hover Tooltip */}
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover/skillOverflow:flex flex-col gap-1 overlay-popover p-2.5 bg-slate-900/95 text-white rounded-xl shadow-xl backdrop-blur-md text-[11px] whitespace-nowrap min-w-[120px] pointer-events-none animate-fade-in border border-slate-700">
            <div className="text-[9px] text-slate-400 font-bold uppercase tracking-wider pb-1 border-b border-slate-800 flex items-center justify-between gap-2">
              <span>待查看技能</span>
              <span>{hiddenSkills.length} 项</span>
            </div>
            <div className="space-y-1 pt-0.5">
              {hiddenSkills.map((hSkill) => {
                const meta = getSkillMeta(hSkill)
                const Icon = meta.icon
                return (
                  <div key={hSkill} className="flex items-center gap-1.5 text-slate-200">
                    <Icon className={`w-3 h-3 ${meta.iconColor} shrink-0`} />
                    <span className="font-semibold text-xs">{meta.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
