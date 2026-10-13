/** Toast 体系：玻璃小卡，右上角，3.5s 自动消失 */
import { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, AlertTriangle, X } from 'lucide-react'

interface Toast { id: number; kind: 'ok' | 'err'; text: string }
const ToastCtx = createContext<{ push: (kind: 'ok' | 'err', text: string) => void }>({ push: () => {} })

export function useToast() { return useContext(ToastCtx) }

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((kind: 'ok' | 'err', text: string) => {
    const id = Date.now() + Math.random()
    setToasts(t => [...t, { id, kind, text }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500)
  }, [])
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]" role="status" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className="glass-l2 animate-in flex items-start gap-2.5 p-3.5 !rounded-card" style={{ borderRadius: 14 }}>
            {t.kind === 'ok'
              ? <CheckCircle2 size={16} style={{ color: 'var(--signal)' }} className="mt-0.5 shrink-0" />
              : <AlertTriangle size={16} style={{ color: 'var(--danger)' }} className="mt-0.5 shrink-0" />}
            <div className="text-[13px] text-t1 leading-snug flex-1">{t.text}</div>
            <button className="text-t3 hover:text-t1 cursor-pointer" onClick={() => setToasts(x => x.filter(y => y.id !== t.id))} aria-label="关闭">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
