import { useEffect, useState } from 'react'
import api from '../api/client'

export default function Blocked() {
  const [list, setList] = useState<any[]>([])
  const load = () => api.get('/firewall/blocked').then(r => setList(r.data)).catch(() => {})
  useEffect(() => { load() }, [])
  return (
    <div className="space-y-5 max-w-4xl animate-in">
      <h1 className="text-[20px] font-bold tracking-tight">封禁管理</h1>
      <div className="l1 overflow-hidden rounded-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-t3 text-xs border-b border-[var(--border)]">
              {['IP', '原因', '操作人', '时间'].map(h => <th key={h} className="px-5 py-3.5 text-left font-medium">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => (
              <tr key={r.ip} className="border-t border-[var(--border)]">
                <td className="px-5 py-3.5 mono text-xs text-t2 border-l-2" style={{ borderLeftColor: 'var(--danger)' }}>{r.ip}</td>
                <td className="px-5 text-t2">{r.reason}</td>
                <td className="px-5 text-t2">{r.blocked_by}</td>
                <td className="px-5 text-t3 text-xs">{r.blocked_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.length && <div className="py-16 flex flex-col items-center gap-2 text-center">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>
          <div className="text-[14px] font-medium text-t1">当前没有封禁的终端</div>
          <div className="text-[12.5px] text-t2">在终端页点击「封禁」后，记录会显示在这里</div>
        </div>}
      </div>
    </div>
  )
}
