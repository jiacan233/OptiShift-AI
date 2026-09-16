import { ArrowUpRight, LoaderCircle } from 'lucide-react'

export function PromptBox({
  value,
  onChange,
  onRun,
  running,
  disabled,
}: {
  value: string
  onChange(value: string): void
  onRun(): void
  running: boolean
  disabled?: boolean
}) {
  return (
    <div className="relative">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') onRun()
        }}
        rows={3}
        className="input-base min-h-[92px] w-full resize-none pb-12 pr-4 leading-6"
        placeholder="例如：E02 周五临时请假，重新排班，其他员工尽量少调整。"
      />
      <div className="absolute inset-x-3 bottom-3 flex items-center justify-between">
        <span className="text-[11px] text-slate-400">Ctrl / ⌘ + Enter 运行</span>
        <button type="button" onClick={onRun} disabled={disabled || running || !value.trim()} className="btn-primary !rounded-lg !px-3 !py-1.5">
          {running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowUpRight className="h-4 w-4" />}
          {running ? '求解中' : '运行'}
        </button>
      </div>
    </div>
  )
}
