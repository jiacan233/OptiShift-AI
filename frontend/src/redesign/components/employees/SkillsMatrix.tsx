import React from 'react'
import { Check, Minus, Sparkles, UserX, RotateCcw } from 'lucide-react'
import { Employee, SkillType } from '../../types/schedule'
import { getCleanName, ROLE_BADGE_STYLES } from './employeeUtils'

interface SkillsMatrixProps {
  employees: Employee[]
  allEmployees: Employee[]
  availableSkills: SkillType[]
  onSelectEmployee: (emp: Employee) => void
  activeSkillFilter?: string
  onSkillFilterChange?: (skill: string) => void
  onClearFilters: () => void
}

export const SkillsMatrix: React.FC<SkillsMatrixProps> = ({
  employees,
  allEmployees,
  availableSkills,
  onSelectEmployee,
  activeSkillFilter = 'all',
  onSkillFilterChange,
  onClearFilters,
}) => {
  const totalEmployeesCount = allEmployees.length

  if (employees.length === 0) {
    return (
      <div className="bg-white rounded-3xl p-12 border border-slate-200/80 shadow-xs flex flex-col items-center justify-center text-center">
        <div className="w-12 h-12 rounded-2xl bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
          <UserX className="w-6 h-6" />
        </div>
        <h3 className="text-sm font-bold text-slate-800">暂无技能矩阵匹配数据</h3>
        <p className="text-xs text-slate-400 mt-1 max-w-sm">
          当前筛选条件下没有匹配的员工，请重置或放宽筛选条件
        </p>
        <button
          onClick={onClearFilters}
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-50 text-blue-600 hover:bg-blue-100 font-bold text-xs transition"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>清除筛选</span>
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3.5">
      {/* Top Skills Coverage Summary Strip */}
      <div className="bg-white rounded-2xl p-3.5 border border-slate-200/80 shadow-xs">
        <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2.5 flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-blue-600" /> 全员技能覆盖统计 (主数据真实配备)
          </span>
          <span className="text-slate-400 font-normal">基于全店 {totalEmployeesCount} 名员工</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {availableSkills.map((skill) => {
            const count = allEmployees.filter((e) => e.skills.includes(skill)).length
            const percentage = Math.round((count / totalEmployeesCount) * 100)
            const isFilterActive = activeSkillFilter === skill

            return (
              <button
                key={skill}
                onClick={() =>
                  onSkillFilterChange &&
                  onSkillFilterChange(isFilterActive ? 'all' : skill)
                }
                className={`p-2.5 rounded-xl border text-left transition ${
                  isFilterActive
                    ? 'bg-blue-50/70 border-blue-400 ring-2 ring-blue-400/20'
                    : 'bg-slate-50/80 border-slate-200/80 hover:bg-slate-100/70 hover:border-slate-300'
                }`}
                title={`点击${isFilterActive ? '取消聚焦' : '仅看具备【' + skill + '】的员工'}`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-800">{skill}</span>
                  <span className="text-xs font-extrabold text-slate-900">
                    {count} <span className="text-[10px] text-slate-400 font-normal">/ {totalEmployeesCount}</span>
                  </span>
                </div>
                <div className="w-full bg-slate-200/70 h-1.5 rounded-full overflow-hidden mt-2">
                  <div
                    className={`h-full rounded-full transition-all ${
                      skill === '店长值守'
                        ? 'bg-blue-600'
                        : skill === '饮品制作'
                        ? 'bg-emerald-600'
                        : skill === '收银'
                        ? 'bg-purple-600'
                        : 'bg-amber-600'
                    }`}
                    style={{ width: `${percentage}%` }}
                  />
                </div>
                <div className="text-[10px] text-slate-400 mt-1 font-semibold flex items-center justify-between">
                  <span>全员占比</span>
                  <span>{percentage}%</span>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Skills Matrix Table */}
      <div className="bg-white rounded-3xl border border-slate-200/80 shadow-xs overflow-hidden">
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/75 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 select-none">
                {/* Employee info (Sticky Left Column) */}
                <th className="py-3 px-4 min-w-[200px] sticky left-0 bg-slate-50/95 z-10 backdrop-blur-xs">
                  员工信息
                </th>

                {/* Dynamic Skills Columns */}
                {availableSkills.map((skill) => (
                  <th
                    key={skill}
                    onClick={() =>
                      onSkillFilterChange &&
                      onSkillFilterChange(activeSkillFilter === skill ? 'all' : skill)
                    }
                    className={`py-3 px-4 text-center min-w-[120px] cursor-pointer hover:text-slate-900 transition ${
                      activeSkillFilter === skill ? 'bg-blue-50/60 text-blue-700' : ''
                    }`}
                    title="点击筛选具备该技能的员工"
                  >
                    <div className="inline-flex items-center gap-1 justify-center">
                      <span>{skill}</span>
                      {activeSkillFilter === skill && (
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-600" />
                      )}
                    </div>
                  </th>
                ))}

                {/* Skill Total */}
                <th className="py-3 px-4 text-center min-w-[90px]">技能合计</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100 text-xs font-medium text-slate-700">
              {employees.map((emp) => {
                const cleanName = getCleanName(emp.name)
                const roleBadgeStyle =
                  ROLE_BADGE_STYLES[emp.role] || 'bg-slate-100 text-slate-600 border-slate-200'

                return (
                  <tr
                    key={emp.id}
                    tabIndex={0}
                  aria-label={`查看 ${emp.id} 员工档案`}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectEmployee(emp) } }}
                  onClick={() => onSelectEmployee(emp)}
                    className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                  >
                    {/* Sticky Employee Column */}
                    <td className="py-3 px-4 sticky left-0 bg-white group-hover:bg-blue-50/60 z-10 transition-colors">
                      <div className="flex items-center gap-3">
                        <img
                          src={emp.avatar}
                          alt={cleanName}
                          className="w-8 h-8 rounded-xl object-cover ring-1 ring-slate-200 group-hover:ring-blue-300 transition shrink-0"
                        />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-slate-900 text-xs truncate">
                              {cleanName}
                            </span>
                            <span
                              className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${roleBadgeStyle}`}
                            >
                              {emp.role}
                            </span>
                          </div>
                          <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                            {emp.id}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Skill Matrix Cells */}
                    {availableSkills.map((skill) => {
                      const hasSkill = emp.skills.includes(skill)
                      const isHighlighted = activeSkillFilter === skill

                      return (
                        <td
                          key={skill}
                          className={`py-3 px-4 text-center ${
                            isHighlighted ? 'bg-blue-50/20' : ''
                          }`}
                        >
                          {hasSkill ? (
                            <div
                              className="inline-flex items-center justify-center w-6 h-6 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-600 font-bold shadow-2xs"
                              title={`${cleanName} · 已认证【${skill}】`}
                            >
                              <Check className="w-3.5 h-3.5" />
                            </div>
                          ) : (
                            <div
                              className="inline-flex items-center justify-center w-6 h-6 text-slate-300"
                              title={`${cleanName} · 未配置【${skill}】`}
                            >
                              <Minus className="w-3.5 h-3.5" />
                            </div>
                          )}
                        </td>
                      )
                    })}

                    {/* Skill Count */}
                    <td className="py-3 px-4 text-center">
                      <span className="inline-block text-xs font-bold text-slate-800 bg-slate-100 px-2 py-0.5 rounded-lg border border-slate-200/60">
                        {emp.skills.length} 项
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
