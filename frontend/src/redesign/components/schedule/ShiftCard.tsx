import React from 'react'
import { ShiftItem } from '../../types/schedule'

interface ShiftCardProps {
  shift: ShiftItem
  onClick?: () => void
}

export const ShiftCard: React.FC<ShiftCardProps> = ({ shift, onClick }) => {
  if (shift.shiftType === 'off') {
    return (
      <div
        onClick={onClick}
        className="h-12 w-full rounded-2xl bg-slate-100/60 flex items-center justify-center text-xs font-semibold text-slate-400 hover:bg-slate-100 transition cursor-pointer select-none"
      >
        {shift.timeRange.includes('限制') ? '限制·Off' : 'Off'}
      </div>
    )
  }

  if (shift.shiftType === 'leave') {
    return (
      <div
        onClick={onClick}
        className="h-12 w-full rounded-2xl bg-rose-50/90 border border-rose-200/80 flex flex-col items-center justify-center text-[10px] font-extrabold text-rose-600 hover:bg-rose-100 transition cursor-pointer select-none px-1 text-center"
        title="员工登记请假 (R-08 绝对不得排班)"
      >
        <span>请假</span>
        <span className="text-[9px] text-rose-400 font-normal">R-08锁定</span>
      </div>
    )
  }

  if (shift.isGhost) {
    // Dropzone slot with dots
    return (
      <div className="h-12 w-full rounded-2xl border-2 border-dashed border-blue-300/80 bg-blue-50/30 flex items-center justify-center text-blue-300">
        <span className="text-sm tracking-widest font-bold opacity-70">···</span>
      </div>
    )
  }

  // Shift color mapping for store shifts:
  // morning: 09:00 - 17:00 早班 (Sky Blue)
  // evening: 13:00 - 21:00 晚班 (Lavender)
  const colorStyles: Record<string, string> = {
    morning: 'bg-[#E1F1FD] text-[#0A6DB7] border border-[#CDE5FC]', // Sky blue
    evening: 'bg-[#EFE8FF] text-[#6938CA] border border-[#E3D4FF]', // Lavender
    day: 'bg-[#E1F7EB] text-[#13854E] border border-[#CBF0DC]',     // Mint green
    mid: 'bg-[#FEF3D6] text-[#B56708] border border-[#FDE5AC]',     // Warm amber
  }

  const currentStyle = colorStyles[shift.shiftType] || colorStyles.morning

  return (
    <div className="relative group">
      {shift.isDragging ? (
        // Active dragging state with hand cursor indicator
        <div className="relative z-10">
          <div
            onClick={onClick}
            className={`h-12 w-full rounded-2xl px-2 py-1.5 flex flex-col justify-center items-center text-center font-semibold text-[11px] leading-[14px] shadow-lg shadow-purple-500/15 ring-2 ring-blue-500/30 cursor-grab ${currentStyle} animate-pulse`}
          >
            <span className="font-bold text-slate-800">{shift.timeRange.split('\n')[0]}</span>
            <span className="text-[10px] opacity-90">{shift.timeRange.split('\n')[1]}</span>
          </div>

          {/* Hand cursor indicator */}
          <div className="absolute -bottom-2 -right-1 pointer-events-none drop-shadow-md">
            <svg
              className="w-5 h-5 text-slate-800"
              viewBox="0 0 24 24"
              fill="white"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0" />
              <path d="M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2" />
              <path d="M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8" />
              <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
            </svg>
          </div>
        </div>
      ) : (
        <div
          onClick={onClick}
          className={`relative h-12 w-full rounded-2xl px-2 py-1 flex flex-col justify-center items-center text-center font-semibold text-[11px] leading-[14px] transition-all hover:scale-[1.02] hover:shadow-sm cursor-pointer select-none ${currentStyle} ${
            shift.violationWarning ? 'ring-2 ring-amber-500/80 bg-amber-50/80' : ''
          }`}
          title={shift.violationWarning}
        >
          {shift.violationWarning && (
            <span
              className="absolute -top-1.5 -right-1 bg-amber-500 text-white text-[9px] font-black px-1.5 py-0.2 rounded-full shadow-sm z-20"
              title={shift.violationWarning}
            >
              {shift.violationWarning}
            </span>
          )}
          <span className="font-bold text-slate-800">{shift.timeRange.split('\n')[0]}</span>
          <span className="text-[10px] opacity-90">{shift.timeRange.split('\n')[1]}</span>
        </div>
      )}
    </div>
  )
}
