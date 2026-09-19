export function CandidateMascot() {
  return <div aria-hidden="true" className="hidden sm:flex relative flex-col items-center shrink-0 w-28 pl-1">
    <div className="relative bg-white border border-slate-200/90 rounded-xl px-2 py-1 shadow-sm text-center mb-1"><p className="text-[10px] font-bold text-slate-700 leading-tight">先预览方案，<br />再确认生效</p><div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-1.5 h-1.5 bg-white border-b border-r border-slate-200 rotate-45" /></div>
    <div className="w-16 h-14 relative flex items-center justify-center">
            <svg
              viewBox="0 0 80 70"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="w-full h-full drop-shadow-sm"
            >
              {/* Antenna */}
              <circle cx="40" cy="8" r="4" fill="#3B82F6" />
              <rect x="38.5" y="10" width="3" height="6" rx="1.5" fill="#93C5FD" />
              {/* Ears / Headset */}
              <rect x="15" y="24" width="5" height="12" rx="2.5" fill="#3B82F6" />
              <rect x="60" y="24" width="5" height="12" rx="2.5" fill="#3B82F6" />
              {/* Head Base */}
              <rect
                x="18"
                y="14"
                width="44"
                height="32"
                rx="14"
                fill="url(#robot_grad)"
                stroke="#DBEAFE"
                strokeWidth="2"
              />
              {/* Visor Screen */}
              <rect
                x="24"
                y="20"
                width="32"
                height="18"
                rx="8"
                fill="#0F172A"
              />
              {/* Glowing Eyes */}
              <ellipse cx="32" cy="29" rx="3.5" ry="4.5" fill="#38BDF8" />
              <ellipse cx="48" cy="29" rx="3.5" ry="4.5" fill="#38BDF8" />
              <circle cx="33.5" cy="27.5" r="1.2" fill="#FFFFFF" />
              <circle cx="49.5" cy="27.5" r="1.2" fill="#FFFFFF" />
              {/* Body */}
              <path
                d="M26 48C26 46 29 45 40 45C51 45 54 46 54 48L56 62C56 64 53 65 40 65C27 65 24 64 24 62L26 48Z"
                fill="url(#robot_body)"
                stroke="#DBEAFE"
                strokeWidth="1.5"
              />
              {/* Chest Indicator */}
              <rect x="34" y="50" width="12" height="6" rx="3" fill="#3B82F6" />
              {/* Waving Right Hand */}
              <path
                d="M55 49Q64 42 66 36Q69 40 65 48Q60 54 56 52"
                fill="#93C5FD"
                stroke="#60A5FA"
                strokeWidth="1"
              />
              {/* Left Arm */}
              <path
                d="M25 49Q18 52 16 57"
                stroke="#93C5FD"
                strokeWidth="3.5"
                strokeLinecap="round"
              />
              <defs>
                <linearGradient id="robot_grad" x1="18" y1="14" x2="62" y2="46" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#FFFFFF" />
                  <stop offset="1" stopColor="#EFF6FF" />
                </linearGradient>
                <linearGradient id="robot_body" x1="24" y1="45" x2="56" y2="65" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#F8FAFC" />
                  <stop offset="1" stopColor="#E2E8F0" />
                </linearGradient>
              </defs>
            </svg>
    </div>
  </div>
}
