/**
 * 网络 → 防火墙：一键放通进站端口与常见场景。
 *
 * 规则统一由后端按语义判重、插在 drop 之前；页面只负责选择条件与展示状态。
 * 用户自己写的等效规则会显示"已有自建规则"，取消时不会被删除。
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, ShieldCheck, ShieldOff, TriangleAlert } from 'lucide-react'
import api from '../api/client'
import { PageHeader, Segmented, Badge, EmptyState, Skeleton, Input, Button } from '../components/ui'
import { ConfirmModal } from '../components/ui/Modal'
import { useToast } from '../components/ui/Toast'

type SceneState = { allowed: boolean; managed: boolean; user_rule: boolean; chains: string[] }

interface Rule {
  id: string
  family: string
  chain: string
  action: string
  protocol: string
  dst_port: string
  in_interface: string
  in_interface_list: string
  src_address: string
  comment: string
  managed: boolean
  effective: boolean
}

interface PortRule {
  protocol: string
  ports: string
  wan: string
  managed: boolean
  user_rule: boolean
  effective: boolean
  chains: string[]
  v4: { allowed: boolean; managed: boolean; user_rule: boolean }
  v6: { allowed: boolean; managed: boolean; user_rule: boolean }
}

interface WanAll {
  wan: string
  v4: SceneState
  v6: SceneState
}

interface ScenesData {
  wans: string[]
  lans: string[]
  has_lan_list: boolean
  has_wan_list: boolean
  rules: Rule[]
  scenes: {
    port_rules: PortRule[]
    lan_all: { v4: SceneState; v6: SceneState }
    wan_all: WanAll[]
  }
}

function StateBadge({ state }: { state: SceneState }) {
  if (state.allowed) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <Badge tone="signal">已放通</Badge>
        {state.user_rule && !state.managed && <Badge tone="ice">你的规则</Badge>}
      </span>
    )
  }
  return <Badge tone="gray">未放通</Badge>
}

export default function NetworkFirewall() {
  const [data, setData] = useState<ScenesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [protocol, setProtocol] = useState<'tcp' | 'udp' | 'both'>('tcp')
  const [portFamily, setPortFamily] = useState<'v4' | 'v6' | 'both'>('v4')
  const [ports, setPorts] = useState('')
  const [wan, setWan] = useState('')
  const [family, setFamily] = useState<'v4' | 'v6' | 'both'>('v4')
  const [confirmWanAll, setConfirmWanAll] = useState(false)
  const toast = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/firewall/scenes')
      setData(res.data)
      setWan(prev => prev || res.data.wans?.[0] || '')
    } catch (e: any) {
      setData(null)
      toast.push('err', e.response?.data?.detail || '读取防火墙规则失败')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const run = async (fn: () => Promise<any>, okText: string) => {
    setBusy(true)
    try {
      const res = await fn()
      const detail = res?.data
      const extra = detail?.user_rule_left ? '（检测到你已有自建规则，未删除）' : ''
      toast.push('ok', okText + extra)
      await load()
    } catch (e: any) {
      toast.push('err', e.response?.data?.detail || '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const submitPort = (enable: boolean) => {
    const value = ports.trim()
    if (!value) { toast.push('err', '先填端口，例如 9233 或 8000-8100'); return }
    if (!wan) { toast.push('err', '先选择 WAN 接口'); return }
    run(() => api.post('/firewall/scenes/port',
      { enable, protocol, ports: value, wan, family: portFamily }),
      enable ? `已放通 ${protocol.toUpperCase()} ${value}（${portFamily === 'both' ? 'IPv4+IPv6' : portFamily.toUpperCase()}，${wan}）`
             : `已取消 ${protocol.toUpperCase()} ${value}（${wan}）`)
  }

  const toggleLanAll = (enable: boolean) =>
    run(() => api.post('/firewall/scenes/lan-all', { enable }),
      enable ? 'LAN 已全部放通' : 'LAN 全部放通已取消')

  const toggleWanAll = (enable: boolean) => {
    if (!wan) { toast.push('err', '先选择 WAN 接口'); return }
    if (enable) { setConfirmWanAll(true); return }
    run(() => api.post('/firewall/scenes/wan-all', { enable: false, family, wan }),
      `已取消 ${wan} 的全部放通`)
  }

  const confirmWanAllApply = () => {
    setConfirmWanAll(false)
    run(() => api.post('/firewall/scenes/wan-all', { enable: true, family, wan }),
      `${wan} 已全部放通`)
  }

  const lanAll = data?.scenes.lan_all
  const wanAll = data?.scenes.wan_all?.find(w => w.wan === wan)
  const relatedRules = data?.rules || []

  return (
    <div>
      <PageHeader
        title="防火墙"
        desc="一键放通进站端口；只管理带 managed-by 标记的规则，不会改动你手写的规则"
        actions={<button className="btn" onClick={load} disabled={busy}><RefreshCw size={14} /> 刷新</button>}
      />

      {loading ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5"><Skeleton h={18} /></div>
          ))}
        </div>
      ) : !data ? (
        <div className="card p-6">
          <EmptyState title="读取不到防火墙规则" desc="检查路由器连接后点刷新重试" />
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {/* 接口概览 */}
          <div className="card p-5 lg:col-span-2">
            <div className="text-[13px] font-semibold mb-3">接口</div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
              <div className="flex items-center gap-2">
                <span className="text-t3">WAN</span>
                {data.wans.length ? data.wans.map(w => (
                  <span key={w} className="mono rounded-md px-2 py-0.5"
                    style={{ background: 'var(--ice-dim)', color: 'var(--ice)' }}>{w}</span>
                )) : <span className="text-t3">未检测到</span>}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-t3">LAN</span>
                {data.lans.length ? data.lans.map(l => (
                  <span key={l} className="mono rounded-md px-2 py-0.5"
                    style={{ background: 'var(--signal-dim)', color: 'var(--signal)' }}>{l}</span>
                )) : <span className="text-t3">未检测到</span>}
              </div>
            </div>
          </div>

          {/* 端口放通 */}
          <div className="card p-5 lg:col-span-2">
            <div className="flex items-center justify-between gap-3 mb-1">
              <div className="text-[13px] font-semibold">放通端口</div>
              <span className="text-[11.5px] text-t3">自动在 input 与 forward 两条链各建一条</span>
            </div>
            <div className="flex flex-wrap items-center gap-2.5 mt-3">
              <Segmented size="sm" value={protocol} onChange={setProtocol} options={[
                { value: 'tcp', label: 'TCP' },
                { value: 'udp', label: 'UDP' },
                { value: 'both', label: '两者' },
              ]} />
              <Segmented size="sm" value={portFamily} onChange={setPortFamily} options={[
                { value: 'v4', label: 'IPv4' },
                { value: 'v6', label: 'IPv6' },
                { value: 'both', label: '全部' },
              ]} />
              <div className="w-44">
                <Input value={ports} onChange={e => setPorts(e.target.value)}
                  placeholder="9233 或 8000-8100" className="mono" />
              </div>
              <div className="w-44">
                <select value={wan} onChange={e => setWan(e.target.value)}
                  className="input mono w-full" aria-label="WAN 接口">
                  {data.wans.map(w => <option key={w} value={w}>{w}</option>)}
                </select>
              </div>
              <Button variant="primary" disabled={busy} onClick={() => submitPort(true)}>
                <ShieldCheck size={14} /> 放通
              </Button>
              <Button disabled={busy} onClick={() => submitPort(false)}>
                <ShieldOff size={14} /> 取消
              </Button>
            </div>

            <div className="mt-4">
              {data.scenes.port_rules.length === 0 ? (
                <div className="text-[12px] text-t3 py-2">还没有放通过端口</div>
              ) : (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>{['协议', '端口', 'WAN', '地址族', '链', '来源', ''].map((h, i) => <th key={i}>{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {data.scenes.port_rules.map(r => (
                        <tr key={`${r.protocol}-${r.ports}-${r.wan}`}>
                          <td>{r.protocol.toUpperCase()}</td>
                          <td className="mono">{r.ports}</td>
                          <td className="mono">{r.wan}</td>
                          <td>
                            <span className="inline-flex gap-1.5">
                              <Badge tone={r.v4.allowed ? 'signal' : 'gray'}>IPv4</Badge>
                              <Badge tone={r.v6.allowed ? 'signal' : 'gray'}>IPv6</Badge>
                            </span>
                          </td>
                          <td className="text-t3">{r.chains.join(' + ') || '—'}</td>
                          <td>
                            {r.managed ? <Badge tone="signal">面板管理</Badge> : <Badge tone="ice">你的规则</Badge>}
                            {!r.effective && <span className="ml-2 text-[11px] text-t3">未生效</span>}
                          </td>
                          <td className="text-right">
                            {r.managed ? (
                              <button className="text-[12px] cursor-pointer"
                                style={{ color: 'var(--danger)' }} disabled={busy}
                                onClick={() => run(() => api.post('/firewall/scenes/port',
                                  { enable: false, protocol: r.protocol, ports: r.ports,
                                    wan: r.wan, family: 'both' }),
                                  `已取消 ${r.protocol.toUpperCase()} ${r.ports}`)}>
                                取消放通
                              </button>
                            ) : <span className="text-[11.5px] text-t3">只读</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* LAN → ALL */}
          <div className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[13px] font-semibold mb-1">LAN → ALL</div>
                <div className="text-[12px] text-t3 leading-relaxed">
                  信任整个内网：允许内网接口访问任何目标。适合"内网默认拒绝"的路由器。
                </div>
              </div>
              {lanAll && (
                <span className="inline-flex gap-1.5 shrink-0 whitespace-nowrap">
                  <Badge tone={lanAll.v4.allowed ? 'signal' : 'gray'}>IPv4</Badge>
                  <Badge tone={lanAll.v6.allowed ? 'signal' : 'gray'}>IPv6</Badge>
                </span>
              )}
            </div>
            {lanAll && (lanAll.v4.user_rule || lanAll.v6.user_rule) && (
              <div className="mt-2 text-[11.5px] text-t3">检测到你已有等效的自建规则，取消时不会删除它。</div>
            )}
            <div className="flex gap-2 mt-4">
              <Button variant="primary" disabled={busy || !data.has_lan_list}
                onClick={() => toggleLanAll(true)}>放通</Button>
              <Button disabled={busy || !data.has_lan_list}
                onClick={() => toggleLanAll(false)}>取消</Button>
              {!data.has_lan_list && <span className="text-[11.5px] text-t3 self-center">没有 LAN 接口列表</span>}
            </div>
          </div>

          {/* WAN → ALL */}
          <div className="card p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[13px] font-semibold mb-1">WAN → ALL</div>
                <div className="text-[12px] text-t3 leading-relaxed">
                  对被选 WAN 放通全部进站流量。放通后请配合 /ip service 的可用源地址限制管理口。
                </div>
              </div>
              {wanAll && (
                <span className="inline-flex gap-1.5 shrink-0 whitespace-nowrap">
                  <Badge tone={wanAll.v4.allowed ? 'signal' : 'gray'}>IPv4</Badge>
                  <Badge tone={wanAll.v6.allowed ? 'signal' : 'gray'}>IPv6</Badge>
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2.5 mt-3">
              <div className="w-40">
                <select value={wan} onChange={e => setWan(e.target.value)}
                  className="input mono w-full" aria-label="WAN 接口">
                  {data.wans.map(w => <option key={w} value={w}>{w}</option>)}
                </select>
              </div>
              <Segmented size="sm" value={family} onChange={setFamily} options={[
                { value: 'v4', label: 'IPv4' },
                { value: 'v6', label: 'IPv6' },
                { value: 'both', label: '全部' },
              ]} />
            </div>
            <div className="flex gap-2 mt-3">
              <Button variant="danger" disabled={busy || !wan}
                onClick={() => toggleWanAll(true)}>放通</Button>
              <Button disabled={busy || !wan} onClick={() => toggleWanAll(false)}>取消</Button>
            </div>
          </div>

          {/* 相关规则 */}
          <div className="card p-5 lg:col-span-2">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[13px] font-semibold">input / forward 现有规则</div>
              <span className="text-[11.5px] text-t3">{relatedRules.length} 条</span>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>{['链', '动作', '匹配', '备注 / 来源', '生效'].map(h => <th key={h}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {relatedRules.map(r => {
                    const match = [
                      `${r.family === 'v6' ? 'v6 ' : ''}${r.protocol ? `${r.protocol}/${r.dst_port || 'any'}` : ''}`.trim(),
                      r.in_interface && `in=${r.in_interface}`,
                      r.in_interface_list && `list=${r.in_interface_list}`,
                      r.src_address && `src=${r.src_address}`,
                    ].filter(Boolean).join('  ') || '全部'
                    return (
                      <tr key={r.id}>
                        <td>{r.chain}</td>
                        <td style={{ color: r.action === 'accept' ? 'var(--signal)' : 'var(--danger)' }}>
                          {r.action}
                        </td>
                        <td className="mono text-[12px]">{match}</td>
                        <td>
                          <span className="text-[12px] text-t2">{r.comment || '—'}</span>
                          {r.managed && <span className="ml-2"><Badge tone="signal">面板</Badge></span>}
                        </td>
                        <td>
                          {r.action === 'accept'
                            ? (r.effective ? '是' : <span className="text-t3">否</span>)
                            : <span className="text-t3">—</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        open={confirmWanAll}
        onClose={() => setConfirmWanAll(false)}
        onConfirm={confirmWanAllApply}
        danger
        title={`放通 ${wan} 的全部流量？`}
        confirmLabel="确认放通"
        desc={`这会在 ${wan} 上放通所有进站流量（${family === 'both' ? 'IPv4 + IPv6' : family === 'v4' ? 'IPv4' : 'IPv6'}）。
路由器的 SSH(22)、Winbox(8291)、www-ssl(443) 等管理服务也会随之暴露，
请确认已在 /ip service 里限制了可用源地址。`}
      />

      <div className="mt-4 flex items-start gap-2 text-[11.5px] text-t3">
        <TriangleAlert size={13} className="mt-0.5 shrink-0" />
        <span>面板只创建/删除带 managed-by=router-panel 标记的规则；你手写的规则只读展示，不会被修改。</span>
      </div>
    </div>
  )
}
