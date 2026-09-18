import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

export function Dialog({ title, onClose, children, wide = false }: { title: string; onClose(): void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement as HTMLElement | null
    dialog.showModal()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { dialog.close(); document.body.style.overflow = overflow; previous?.focus() }
  }, [])
  return <dialog ref={ref} aria-label={title} onCancel={event => { event.preventDefault(); onClose() }} className={`m-auto max-h-[90dvh] w-[calc(100%-24px)] rounded-3xl border-0 bg-white p-0 text-slate-800 shadow-2xl backdrop:bg-slate-900/30 backdrop:backdrop-blur-sm ${wide ? 'max-w-3xl' : 'max-w-lg'}`}>
    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-4"><h2 className="font-extrabold">{title}</h2><button onClick={onClose} aria-label={`关闭${title}`} className="rounded-xl p-2 hover:bg-slate-100"><X className="h-5 w-5" /></button></div>
    <div className="p-5">{children}</div>
  </dialog>
}
