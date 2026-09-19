import React, { useState, useEffect } from 'react'
import { X, ChevronLeft, ChevronRight, Calendar, User, Clock, Home, ArrowLeftRight } from 'lucide-react'

interface MobilePreviewProps {
  isOpen: boolean
  onClose: () => void
}

export const MobilePreview: React.FC<MobilePreviewProps> = ({ isOpen, onClose }) => {
  const [seconds, setSeconds] = useState(0)
  const [isClockedIn, setIsClockedIn] = useState(false)

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | undefined
    if (isClockedIn) {
      interval = setInterval(() => {
        setSeconds((prev) => prev + 1)
      }, 1000)
    } else if (interval) {
      clearInterval(interval)
    }
    return () => {
      if (interval) clearInterval(interval)
    }
  }, [isClockedIn])

  const formatTime = (totalSec: number) => {
    const hrs = String(Math.floor(totalSec / 3600)).padStart(2, '0')
    const mins = String(Math.floor((totalSec % 3600) / 60)).padStart(2, '0')
    const secs = String(totalSec % 60).padStart(2, '0')
    return `${hrs}:${mins}:${secs}`
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-md overflow-y-auto">
      <div className="relative max-w-5xl w-full my-8">
        {/* Close Button */}
        <div className="flex justify-between items-center mb-4 text-white">
          <div className="flex items-center gap-2">
            <span className="text-xl">📱</span>
            <h2 className="text-lg font-bold">Mobile Companion Screens (As seen in target UI)</h2>
          </div>
          <button
            onClick={onClose}
            className="w-9 h-9 rounded-full bg-white/20 hover:bg-white/30 text-white flex items-center justify-center transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Dual Phone Display */}
        <div className="flex flex-wrap items-center justify-center gap-10">
          {/* Phone 1: My Shifts */}
          <div className="w-[300px] h-[590px] bg-slate-50 rounded-[44px] p-3 shadow-2xl border-[6px] border-white ring-1 ring-slate-200 flex flex-col justify-between overflow-hidden">
            <div>
              {/* Status Bar */}
              <div className="flex justify-between items-center px-4 pt-1 text-[11px] font-bold text-slate-400">
                <span>9:41</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px]">5G</span>
                  <div className="w-4 h-2 border border-slate-400 rounded-sm" />
                </div>
              </div>

              {/* Blue Header */}
              <div className="mt-2 bg-blue-600 text-white rounded-3xl p-3.5 shadow-md shadow-blue-500/20">
                <div className="flex items-center justify-between">
                  <ChevronLeft className="w-4 h-4 cursor-pointer" />
                  <span className="text-xs font-bold">My shifts</span>
                  <div className="w-4" />
                </div>

                {/* Calendar strip */}
                <div className="mt-3 flex items-center justify-between text-xs px-1">
                  <ChevronLeft className="w-3.5 h-3.5 text-blue-200 cursor-pointer" />
                  <span className="text-[11px] font-semibold">May 18</span>
                  <ChevronRight className="w-3.5 h-3.5 text-blue-200 cursor-pointer" />
                </div>

                {/* Days numbers */}
                <div className="mt-2 flex justify-between items-center text-[10px] font-semibold text-blue-100">
                  {['12', '13', '14', '15', '16', '17', '18'].map((d) => (
                    <div
                      key={d}
                      className={`w-6 h-6 rounded-full flex items-center justify-center ${
                        d === '15' ? 'bg-white text-blue-700 font-extrabold shadow-sm' : ''
                      }`}
                    >
                      {d}
                    </div>
                  ))}
                </div>
              </div>

              {/* Content */}
              <div className="p-3 space-y-3">
                <div className="bg-white rounded-2xl p-3 border border-slate-100 shadow-sm">
                  <div className="text-[11px] font-bold text-slate-500 mb-1.5">Today, Thu May 15</div>
                  <div className="bg-emerald-50 text-emerald-700 border border-emerald-100 rounded-xl py-1 px-3 text-center text-xs font-bold">
                    Off
                  </div>
                </div>

                <div className="bg-white rounded-2xl p-3 border border-slate-100 shadow-sm space-y-2">
                  <div className="text-[11px] font-bold text-slate-500">Upcoming shifts</div>
                  <div className="space-y-1.5 text-xs">
                    <div className="p-2 rounded-xl bg-slate-50 flex justify-between items-center">
                      <span className="font-semibold text-slate-700">Fri, May 16</span>
                      <span className="font-bold text-blue-600">8:00 AM - 4:00 PM</span>
                    </div>
                    <div className="p-2 rounded-xl bg-slate-50 flex justify-between items-center">
                      <span className="font-semibold text-slate-700">Sat, May 17</span>
                      <span className="font-bold text-blue-600">8:00 AM - 4:00 PM</span>
                    </div>
                    <div className="p-2 rounded-xl bg-slate-50 flex justify-between items-center">
                      <span className="font-semibold text-slate-700">Sun, May 18</span>
                      <span className="font-bold text-blue-600">8:00 AM - 4:00 PM</span>
                    </div>
                  </div>
                </div>

                <button className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-2xl shadow-sm transition flex items-center justify-center gap-1.5">
                  <ArrowLeftRight className="w-3.5 h-3.5" />
                  Request swap
                </button>
              </div>
            </div>

            {/* Bottom Nav */}
            <div className="flex justify-around items-center border-t border-slate-100 py-2.5 bg-white rounded-b-3xl">
              <Calendar className="w-4 h-4 text-blue-600" />
              <User className="w-4 h-4 text-slate-400" />
              <Clock className="w-4 h-4 text-slate-400" />
            </div>
          </div>

          {/* Phone 2: Time Clock */}
          <div className="w-[300px] h-[590px] bg-slate-50 rounded-[44px] p-3 shadow-2xl border-[6px] border-white ring-1 ring-slate-200 flex flex-col justify-between overflow-hidden">
            <div>
              {/* Status Bar */}
              <div className="flex justify-between items-center px-4 pt-1 text-[11px] font-bold text-slate-400">
                <span>9:41</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px]">5G</span>
                  <div className="w-4 h-2 border border-slate-400 rounded-sm" />
                </div>
              </div>

              {/* Blue Header */}
              <div className="mt-2 bg-blue-600 text-white rounded-3xl p-3.5 shadow-md shadow-blue-500/20">
                <div className="flex items-center justify-between">
                  <ChevronLeft className="w-4 h-4 cursor-pointer" />
                  <span className="text-xs font-bold">Time clock</span>
                  <div className="w-4" />
                </div>
              </div>

              {/* Main Content */}
              <div className="p-4 flex flex-col items-center text-center">
                <div className="text-xs font-semibold text-slate-600">Good morning, Ava</div>
                <div className="text-[10px] text-slate-400 mt-0.5">May 15, 2025</div>

                {/* Stopwatch Dial */}
                <div className="relative w-40 h-40 my-6 flex items-center justify-center">
                  <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      fill="transparent"
                      stroke="#E2E8F0"
                      strokeWidth="6"
                    />
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      fill="transparent"
                      stroke={isClockedIn ? '#10B981' : '#F59E0B'}
                      strokeWidth="6"
                      strokeDasharray={2 * Math.PI * 42}
                      strokeDashoffset={isClockedIn ? (seconds % 60) * 4 : 200}
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="absolute flex flex-col items-center">
                    <span className="text-2xl font-black text-slate-800 tracking-tight font-mono">
                      {formatTime(seconds)}
                    </span>
                    <span className="text-[10px] font-medium text-slate-400 mt-1">
                      {isClockedIn ? 'Working now' : 'Not clocked in'}
                    </span>
                  </div>
                </div>

                {/* Clock In / Out button */}
                <button
                  onClick={() => setIsClockedIn(!isClockedIn)}
                  className={`w-full py-3 text-white text-xs font-bold rounded-2xl shadow-md transition ${
                    isClockedIn
                      ? 'bg-rose-600 hover:bg-rose-700 shadow-rose-600/20'
                      : 'bg-emerald-600 hover:bg-emerald-700 shadow-emerald-600/20'
                  }`}
                >
                  {isClockedIn ? 'Clock out' : 'Clock in'}
                </button>

                <button className="mt-3 text-[11px] font-semibold text-blue-600 hover:underline">
                  View timesheet
                </button>
              </div>
            </div>

            {/* Bottom Nav */}
            <div className="flex justify-around items-center border-t border-slate-100 py-2.5 bg-white rounded-b-3xl">
              <Home className="w-4 h-4 text-slate-400" />
              <Calendar className="w-4 h-4 text-slate-400" />
              <Clock className="w-4 h-4 text-blue-600" />
              <User className="w-4 h-4 text-slate-400" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
