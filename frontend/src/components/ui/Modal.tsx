/** 统一 Modal（玻璃 L2）+ ConfirmModal；ESC 关闭 */
import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export function Modal({ open, onClose, title, children, width = 440 }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; width?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    ref.current?.querySelector<HTMLElement>('button, input, [tabindex]')?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-[90] p-4" style={{ background: 'rgba(0,0,0,0.4)' }} onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={ref} className="glass-l2 modal-static w-full flex flex-col overflow-hidden absolute left-1/2 top-1/2"
        style={{ maxWidth: width, maxHeight: 'min(88vh, 760px)', minHeight: 0, borderRadius: 18,
                 transform: 'translate(-50%, -50%)' }} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-center justify-between px-5 pt-4 pb-1 shrink-0">
          <h2 className="text-[15px] font-bold">{title}</h2>
          <button onClick={onClose} className="text-t3 hover:text-t1 cursor-pointer" aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="px-5 pb-5 overflow-auto min-h-0">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmModal({ open, onClose, onConfirm, title, desc, confirmLabel = '确认', danger }:
  { open: boolean; onClose: () => void; onConfirm: () => void; title: string; desc?: string; confirmLabel?: string; danger?: boolean }) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      {desc && <p className="text-[13px] text-t2 leading-relaxed mb-5">{desc}</p>}
      <div className="flex gap-2.5 justify-end">
        <button onClick={onClose} className="h-9 px-4 rounded-ctrl border border-[var(--border)] text-[13px] text-t2 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer">取消</button>
        <button onClick={() => { onConfirm(); onClose() }}
          className="h-9 px-4 rounded-ctrl text-[13px] font-semibold text-white cursor-pointer hover:opacity-90"
          style={{ background: danger ? 'var(--danger)' : 'var(--signal)', color: danger ? '#fff' : '#000' }}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}
