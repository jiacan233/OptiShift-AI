import React from 'react'
import { Employee } from '../../types/schedule'
import { getCleanName } from '../employees/employeeUtils'

interface AssignedEmployeeChipProps {
  employee: Employee
  onClick: (employee: Employee) => void
  warning?: string
}

export const AssignedEmployeeChip: React.FC<AssignedEmployeeChipProps> = ({
  employee,
  onClick,
  warning,
}) => {
  const cleanName = getCleanName(employee.name)

  return (
    <button
      type="button"
      onClick={() => onClick(employee)}
      className={`group relative inline-flex items-center gap-1.5 pl-1 pr-2.5 py-1 rounded-full bg-white hover:bg-blue-50/80 border ${
        warning ? 'border-amber-400 bg-amber-50/50' : 'border-slate-200/90'
      } hover:border-blue-300 shadow-2xs hover:shadow-xs transition-all cursor-pointer select-none text-left`}
      title={warning ? `${cleanName} (${employee.role}) - ${warning}` : `点击查看 ${cleanName} (${employee.role}) 的详细档案`}
    >
      {warning && (
        <span
          className="absolute -top-1 -right-1 bg-amber-500 text-white text-[8px] font-black px-1 rounded-full shadow-xs"
          title={warning}
        >
          ⚠
        </span>
      )}
      <img
        src={employee.avatar}
        alt={cleanName}
        className="w-6 h-6 rounded-full object-cover ring-1 ring-slate-200/90 group-hover:ring-blue-400 transition shrink-0"
      />
      <span className="text-xs font-bold text-slate-800 group-hover:text-blue-600 transition truncate max-w-[72px]">
        {cleanName}
      </span>
      <span className="text-[10px] font-medium text-slate-400 group-hover:text-slate-600 transition shrink-0">
        {employee.role}
      </span>
    </button>
  )
}
