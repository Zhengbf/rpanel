/** 全局 UI 状态（纯 React，不引 zustand 新依赖思路——但项目已有 zustand，直接用） */
import { create } from 'zustand'

export type Theme = 'dark' | 'light'
export type FxMode = 'full' | 'off'

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t
}
function applyFx(m: FxMode) {
  document.documentElement.dataset.fx = m
}

interface UiState {
  theme: Theme
  fx: FxMode
  sidebarCollapsed: boolean
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setFx: (m: FxMode) => void
  toggleSidebar: () => void
}

const prefersDark = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches

export const useUi = create<UiState>((set, get) => ({
  theme: (localStorage.getItem('rp-theme') as Theme) || (prefersDark ? 'dark' : 'light'),
  fx: (localStorage.getItem('rp-fx') as FxMode) || 'full',
  sidebarCollapsed: localStorage.getItem('rp-sidebar') === '1',
  setTheme: t => { applyTheme(t); localStorage.setItem('rp-theme', t); set({ theme: t }) },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  setFx: m => { applyFx(m); localStorage.setItem('rp-fx', m); set({ fx: m }) },
  toggleSidebar: () => {
    const v = !get().sidebarCollapsed
    localStorage.setItem('rp-sidebar', v ? '1' : '0')
    set({ sidebarCollapsed: v })
  },
}))

/** 初始化时应用一次 */
export function initUi() {
  const s = useUi.getState()
  applyTheme(s.theme)
  applyFx(s.fx)
}
