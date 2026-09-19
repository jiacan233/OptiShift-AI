import React from 'react'
import { ArrowLeftRight } from 'lucide-react'

interface SwapBadgeProps {
  user1Avatar: string
  user2Avatar: string
  statusText?: string
  onClick?: () => void
}

export const SwapBadge: React.FC<SwapBadgeProps> = ({
  user1Avatar,
  user2Avatar,
  statusText = 'Swap requested',
  onClick,
}) => {
  return (
    <div
      onClick={onClick}
      className="bg-white/95 backdrop-blur-sm border border-slate-200/80 rounded-2xl p-2 px-3 shadow-lg shadow-slate-200/50 flex flex-col items-center gap-1 cursor-pointer hover:scale-105 transition-all select-none"
    >
      <div className="flex items-center gap-2">
        <img
          src={user1Avatar}
          alt="Employee 1"
          className="w-7 h-7 rounded-full object-cover ring-2 ring-emerald-100"
        />
        <div className="w-5 h-5 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center">
          <ArrowLeftRight className="w-3 h-3 stroke-[2.5]" />
        </div>
        <img
          src={user2Avatar}
          alt="Employee 2"
          className="w-7 h-7 rounded-full object-cover ring-2 ring-emerald-100"
        />
      </div>
      <span className="text-[10px] font-bold text-slate-700 tracking-tight">
        {statusText}
      </span>
    </div>
  )
}
