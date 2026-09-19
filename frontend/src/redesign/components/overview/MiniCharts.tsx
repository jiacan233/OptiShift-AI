import React from 'react'

export const MiniBarChart: React.FC = () => {
  // 7 vertical bars representing days
  const heights = [40, 65, 85, 60, 95, 80, 90]
  return (
    <div className="flex items-end justify-between gap-1.5 h-9 w-24 pt-1">
      {heights.map((h, i) => (
        <div
          key={i}
          style={{ height: `${h}%` }}
          className="w-2 bg-blue-600 rounded-sm hover:bg-blue-700 transition-all"
        />
      ))}
    </div>
  )
}

export const Sparkline: React.FC<{
  color?: string
  fillColor?: string
  trend?: 'up' | 'down'
}> = ({
  color = '#10B981',
}) => {
  // SVG curved sparkline
  return (
    <div className="h-8 w-24">
      <svg viewBox="0 0 100 35" className="w-full h-full overflow-visible">
        <defs>
          <linearGradient id={`grad-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        {/* Fill area */}
        <path
          d="M 0,25 Q 20,28 35,18 T 65,22 T 85,10 L 100,6 L 100,35 L 0,35 Z"
          fill={`url(#grad-${color.replace('#', '')})`}
        />
        {/* Line */}
        <path
          d="M 0,25 Q 20,28 35,18 T 65,22 T 85,10 L 100,6"
          fill="none"
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    </div>
  )
}
