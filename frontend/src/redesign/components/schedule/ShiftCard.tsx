import type { ShiftItem } from '../../types/schedule'

export function ShiftCard({ shift, onClick }: { shift: ShiftItem; onClick?(): void }) {
  const colors = { morning: 'bg-[#E1F1FD] text-[#0A6DB7] border-[#CDE5FC]', evening: 'bg-[#EFE8FF] text-[#6938CA] border-[#E3D4FF]', off: 'bg-slate-50 text-slate-400 border-transparent', leave: 'bg-rose-50 text-rose-600 border-rose-200' }
  const Element = onClick ? 'button' : 'div'
  return <Element onClick={onClick} className={`flex h-12 w-full flex-col items-center justify-center rounded-2xl border px-1 text-[11px] font-semibold leading-4 transition hover:brightness-95 ${colors[shift.shiftType]}`}>
    {shift.timeRange.split('\n').map((line, i) => <span key={i} className={i ? 'text-[10px] opacity-80' : ''}>{line}</span>)}
  </Element>
}
