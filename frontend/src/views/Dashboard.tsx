/**
 * 总览：Signal Glass Bento
 * ① 英雄 WAN 实时流量（8 栏，首屏）② KPI 竖列（4 栏，含 sparkline）
 * ③ 线路与接口 ④ 系统资源（MeterLED）⑤ CPU/内存历史 ⑥ 排行 ⑦ 新设备横幅
 * 业务逻辑与 API/WS 契约与旧版一致。
 */
import { useEffect, useRef, useState, useMemo } from 'react'
import { ArrowDown, ArrowUp, MonitorSmartphone, ShieldBan, Globe, Cpu, Activity, Eye, EyeOff, Trophy } from 'lucide-react'
import { echarts, chartTheme } from '../charts/theme'
import { RingSeries } from '../lib/sparkline'
import { useUi } from '../lib/store'
import { fmtUptime, fmtBytes, fmtRate } from '../lib/format'
import { Sparkline } from '../components/ui/Sparkline'
import { StatBlock, MeterLED, Segmented, PageHeader, Card } from '../components/ui'
import { useWebSocket } from '../ws/useWebSocket'
import AlertBar from '../components/AlertBar'
import api from '../api/client'

type Win = '5m' | '1h' | '24h'
const DASH = '—'

export default function Dashboard() {
  const theme = useUi(s => s.theme)
  const [wan, setWan] = useState<any>({ total: { rx: 0, tx: 0 }, interfaces: {} })
  const [sys, setSys] = useState<any>(null)
  const [ov, setOv] = useState<any>(null)
  const [win, setWin] = useState<Win>(() => {
    const q = new URLSearchParams(location.search).get('win')
    return q === '1h' || q === '24h' ? q : '5m'
  })
  const [showWanIp, setShowWanIp] = useState(false)
  const [rankPeriod, setRankPeriod] = useState<'today' | '7d' | '30d'>('today')
  const [ranking, setRanking] = useState<any[]>([])
  const [rankOpen, setRankOpen] = useState(false)
  const [sysState, setSysState] = useState<any>(null)

  // KPI sparkline 环形缓冲（前端轮询，不改后端）
  const rxRing = useRef(new RingSeries(600))
  const txRing = useRef(new RingSeries(600))
  const devRing = useRef(new RingSeries(600))
  const [sparks, setSparks] = useState<{ rx: Array<[number, number]>; tx: Array<[number, number]>; dev: Array<[number, number]> }>({ rx: [], tx: [], dev: [] })

  useWebSocket(['wan', 'sys'], (topic, data) => {
    if (topic === 'wan') {
      setWan(data)
      rxRing.current.push(data.total.rx)
      txRing.current.push(data.total.tx)
      window.dispatchEvent(new Event('rp-ws-msg'))
    } else if (topic === 'sys') setSys(data)
  })

  useEffect(() => {
    const load = () => api.get('/dashboard/overview').then(r => {
      setOv(r.data)
      devRing.current.push(r.data.online_count ?? 0)
    }).catch(() => {})
    load()
    const t = setInterval(load, 3000)
    const loadState = () => api.get('/system/status').then(r => setSysState(r.data)).catch(() => {})
    loadState()
    const t2 = setInterval(loadState, 8000)
    return () => { clearInterval(t); clearInterval(t2) }
  }, [])

  // 每 2s 把环形缓冲刷进 sparkline state
  useEffect(() => {
    const t = setInterval(() => setSparks({ rx: rxRing.current.series(), tx: txRing.current.series(), dev: devRing.current.series() }), 2000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    api.get(`/alerts/ranking?period=${rankPeriod}`).then(r => setRanking(r.data)).catch(() => {})
  }, [rankPeriod])

  const wanChartRef = useRef<HTMLDivElement>(null)
  const sysChartRef = useRef<HTMLDivElement>(null)
  const wanChart = useRef<echarts.ECharts>()
  const sysChart = useRef<echarts.ECharts>()

  // 英雄 WAN 图：照 OpenWrt 的流量图画。
  //
  // 特征是「上下行共用一条纵轴 + 两个半透明填充尖峰互相叠着」，靠面积
  // 大小直接比吞吐，而不是各占一条轴。所以这里刻意不做平滑（smooth 会
  // 把尖峰抹圆）、不画数据点，只保留折线轮廓和填充。
  useEffect(() => {
    if (!wanChartRef.current) return
    wanChart.current = wanChart.current || echarts.init(wanChartRef.current)
    const t = chartTheme()
    const spanMs = { '5m': 300_000, '1h': 3_600_000, '24h': 86_400_000 }[win]
    const nowMs = Date.now()

    // 固定时间槽，即使后端数据还没攒满也占满整个窗口宽度，
    // 这样 5 分钟 / 1 小时 / 24 小时三档的时间跨度一眼能区分开。
    const SLOTS = 90
    const slotMs = spanMs / SLOTS
    const slotTs = Array.from({ length: SLOTS }, (_, i) => nowMs - (SLOTS - 1 - i) * slotMs)
    const timeLabel = (ts: number) => {
      const d = new Date(ts)
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      if (win === '24h') return `${hh}:${mm}`
      const ss = String(d.getSeconds()).padStart(2, '0')
      return `${hh}:${mm}:${ss}`
    }
    const toSlots = (pts: any[], key: 'rx' | 'tx') => {
      const out: (number | null)[] = Array(SLOTS).fill(null)
      // 只取最近 SLOTS 个点，否则窗口数据多的时候会画成最旧的一段
      const recent = pts.slice(-SLOTS)
      const offset = SLOTS - recent.length
      recent.forEach((p, i) => {
        const slot = offset + i
        if (slot < SLOTS) out[slot] = p[key]
      })
      return out
    }

    // points 与 SLOTS 保持一致：后端多给的点会被丢掉，少给就会在左侧留空
    const load = () => api.get(`/dashboard/wan/history?window=${win}&points=${SLOTS}`).then(r => {
      const pts: any[] = r.data.points || []
      wanChart.current?.setOption({
        animation: false,
        grid: { left: 68, right: 20, top: 14, bottom: 24 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: t.card, borderColor: t.grid,
          textStyle: { color: t.text, fontFamily: 'Geist Mono', fontSize: 11 },
          axisPointer: { lineStyle: { color: t.grid } },
          valueFormatter: (v: number | null) => (v == null ? '—' : fmtRate(Number(v))),
        },
        // 分类轴：用等长的时间槽做刻度，线条才会均匀铺满整个窗口
        xAxis: {
          type: 'category',
          data: slotTs.map(timeLabel),
          boundaryGap: true,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: t.text, fontSize: 10, interval: Math.floor(SLOTS / 5) },
        },
        // OpenWrt 的取舍：上下行同规，靠面积大小比吞吐
        yAxis: {
          type: 'value',
          splitLine: { lineStyle: { color: t.grid, type: 'dashed' } },
          axisLabel: { color: t.text, fontSize: 10, formatter: (v: number) => fmtRate(v) },
        },
        // 先画上行再画下行，下行压在上层，重叠处自然混色
        series: [
          { name: '上行', type: 'line', smooth: false, showSymbol: false,
            lineStyle: { width: 1.3, color: t.ice },
            areaStyle: { color: t.ice, opacity: 0.42, origin: 'start' },
            data: toSlots(pts, 'tx') },
          { name: '下行', type: 'line', smooth: false, showSymbol: false,
            lineStyle: { width: 1.3, color: t.signal },
            areaStyle: { color: t.signal, opacity: 0.38, origin: 'start' },
            data: toSlots(pts, 'rx') },
        ],
        // category 轴的类目会随刷新变化，保留合并以免动画期间闪断
      }, { notMerge: false })
    }).catch(() => {})

    load()
    // 图表挂在"实时"区，隔几秒重画一次，否则看起来像冻结的截图
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [win, theme])

  // CPU/内存历史
  useEffect(() => {
    if (!sysChartRef.current) return
    sysChart.current = sysChart.current || echarts.init(sysChartRef.current)
    const t = chartTheme()
    const spanMs = { '5m': 300_000, '1h': 3_600_000, '24h': 86_400_000 }[win]
    const nowMs = Date.now()
    api.get(`/dashboard/sys/history?window=${win}`).then(r => {
      sysChart.current?.setOption({
        animation: false,
        grid: { left: 44, right: 16, top: 12, bottom: 24 },
        tooltip: { trigger: 'axis', backgroundColor: t.card, borderColor: t.grid,
                   textStyle: { color: t.text, fontFamily: 'Geist Mono', fontSize: 11 },
                   valueFormatter: (v: number) => v.toFixed(1) + '%' },
        xAxis: { type: 'time', min: nowMs - spanMs, max: nowMs,
                 axisLine: { show: false }, axisTick: { show: false },
                 axisLabel: { color: t.text, fontSize: 10 } },
        yAxis: { type: 'value', max: 100, splitLine: { lineStyle: { color: t.grid, type: 'dashed' } },
                 axisLabel: { color: t.text, fontSize: 10, formatter: '{value}%' } },
        series: [
          { name: 'CPU', type: 'line', smooth: true, showSymbol: false,
            lineStyle: { width: 1.8, color: t.text }, data: r.data.cpu.map((p: any) => [p.ts * 1000, p.rx]) },
          { name: '内存', type: 'line', smooth: true, showSymbol: false,
            lineStyle: { width: 1.8, color: t.ice }, data: r.data.mem.map((p: any) => [p.ts * 1000, p.rx]) },
        ],
      })
    })
  }, [win, theme])

  // 兜底：WS 首帧到达前用 overview 的 HTTP 快照
  const wanIfaces = Object.entries(wan.interfaces) as [string, any][]
  const detected = (ov?.wan_interfaces ?? []) as string[]
  const ipList = (ov?.ip_addresses ?? []) as any[]
  const sysInfo = ov?.system

  const rxNow = wan.total.rx || ov?.current_rx || 0
  const txNow = wan.total.tx || ov?.current_tx || 0
  const cpuNow = sys?.cpu ?? sysInfo?.cpu_load ?? 0
  const memUsed = sys?.mem_used ?? ov?.mem_used ?? 0
  const memTotal = sys?.mem_total ?? ov?.mem_total ?? 0
  const memPct = sys?.mem ?? (memTotal ? (memUsed / memTotal) * 100 : 0)

  const maskIp = (ip: string) => {
    if (!showWanIp) {
      const parts = ip.split('.')
      if (parts.length === 4 && !ip.startsWith('192.168.') && !ip.startsWith('10.') && !ip.startsWith('172.')) {
        return parts[0] + '.' + parts[1] + '.••••'
      }
    }
    return ip
  }

  const isZero = (v: number) => !v || v < 1

  return (
    <div className="animate-in">
      <AlertBar />
      {sysState && sysState.state !== 'ok' && (
        <div className="card px-5 py-4 mb-4 flex flex-wrap items-center gap-3"
          style={{ borderColor: sysState.state === 'unbound' ? 'var(--border-strong)' : 'color-mix(in srgb, var(--danger) 45%, transparent)' }}>
          <span className="status-dot" style={{ background: sysState.state === 'unbound' ? 'var(--text-3)' : 'var(--danger)' }} />
          <span className="text-[13px] font-medium">
            {sysState.state === 'unbound' ? '尚未绑定路由器设备'
              : sysState.state === 'stopped' ? '已绑定设备，但采样服务未启动（重启面板即可）'
              : '已绑定设备，但当前无法连接路由器'}
          </span>
          <span className="text-[12.5px] text-t2">
            {sysState.state === 'unbound'
              ? '绑定后才能看到 WAN 流量、终端与线路数据。'
              : sysState.device_host ? `目标 ${sysState.device_host}，请检查网络或路由器服务是否可用。` : ''}
          </span>
          {sysState.state === 'unbound' && (
            <a href="/wizard" className="btn ml-auto">去绑定设备</a>
          )}
        </div>
      )}
      <PageHeader
        title="总览"
        desc={<>{ov?.identity || 'RouterOS'} · {sysInfo?.version || DASH} · 已运行 {fmtUptime(sysInfo?.uptime || '')}</>}
        actions={<Segmented value={win} onChange={setWin} size="sm"
          options={[{ value: '5m', label: '5 分钟' }, { value: '1h', label: '1 小时' }, { value: '24h', label: '24 小时' }]} />}
      />

      {/* Bento ① 英雄 WAN + ② KPI 列 */}
      <div className="grid gap-4 mb-4 items-stretch" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)' }}>
        {/* ① 英雄：WAN 实时流量 */}
        <Card className="flex flex-col" style={{ minHeight: 340 }}>
          <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3 mb-2">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-t3 mono flex items-center gap-1.5">
                <ArrowDown size={12} className="text-signal" /> 下行
              </div>
              <div className="mono font-semibold leading-none mt-1" style={{ fontSize: 'var(--fs-display)', color: 'var(--signal)' }}>
                {fmtRate(rxNow).replace(/ (B|KB|MB|GB)\/s$/, '')}
                <span className="unit ml-1.5">{(fmtRate(rxNow).match(/ (B|KB|MB|GB)\/s$/) || ['', 'B/s'])[1] + '/s'}</span>
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-t3 mono flex items-center gap-1.5">
                <ArrowUp size={12} className="text-ice" /> 上行
              </div>
              <div className="mono font-semibold leading-none mt-1" style={{ fontSize: 'var(--fs-display)', color: 'var(--ice)' }}>
                {fmtRate(txNow).replace(/ (B|KB|MB|GB)\/s$/, '')}
                <span className="unit ml-1.5">{(fmtRate(txNow).match(/ (B|KB|MB|GB)\/s$/) || ['', 'B/s'])[1] + '/s'}</span>
              </div>
            </div>
          </div>
          <div ref={wanChartRef} className="w-full flex-1" style={{ minHeight: 190 }} />
        </Card>

        {/* ② KPI 竖列 */}
        <Card className="flex flex-col justify-between gap-5">
          <StatBlock label="总下行" tone="signal" value={fmtRate(rxNow)} spark={<Sparkline data={sparks.rx} color="var(--signal)" />} />
          <StatBlock label="总上行" tone="ice" value={fmtRate(txNow)} spark={<Sparkline data={sparks.tx} color="var(--ice)" />} />
          <StatBlock label="在线终端" value={String(ov?.online_count ?? DASH)} tone={undefined}
            sub={ov ? `/ ${ov.device_count}` : undefined}
            spark={<Sparkline data={sparks.dev} color="var(--text-3)" height={24} />} />
          <StatBlock label="封禁中" tone={(ov?.blocked_count ?? 0) > 0 ? 'danger' : undefined}
            value={String(ov?.blocked_count ?? DASH)} />
        </Card>
      </div>

      {/* Bento ③ 线路 + ④ 系统资源 */}
      <div className="grid gap-3.5 mb-3.5 lg:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between mb-3.5">
            <div className="flex items-center gap-2 text-[13.5px] font-semibold">
              <Globe size={15} className="text-t2" /> 线路与接口
            </div>
            <button onClick={() => setShowWanIp(v => !v)} aria-label={showWanIp ? '隐藏公网 IP' : '显示公网 IP'}
              className="text-t3 hover:text-t1 cursor-pointer">
              {showWanIp ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          <div className="flex flex-col gap-2.5">
            {(wanIfaces.length ? wanIfaces : detected.map(n => [n, { rx: 0, tx: 0 }] as [string, any])).map(([name, d]) => {
              const ipInfo = ipList.find((x: any) => x.interface === name)
              const wanIp = ipInfo?.address?.split('/')[0]
              const total = d.rx + d.tx
              const maxTotal = Math.max(1, ...Object.values(wan.interfaces).map((x: any) => x.rx + x.tx))
              return (
                <div key={name} className="rounded-ctrl border border-[var(--border)] px-3.5 py-2.5"
                  style={isZero(total) ? { opacity: 0.45 } : undefined}>
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`status-dot ${total > 1 ? 'on' : 'off'}`} style={{ width: 6, height: 6 }} />
                      <span className="mono text-[12.5px] font-semibold truncate">{name}</span>
                      {wanIp && <span className="mono text-[11px] text-t3 hidden md:inline">{maskIp(wanIp)}</span>}
                    </div>
                    <div className="mono text-[12.5px] flex gap-3 shrink-0">
                      <span className="text-signal">↓ {fmtRate(d.rx)}</span>
                      <span className="text-ice">↑ {fmtRate(d.tx)}</span>
                    </div>
                  </div>
                  <div className="mt-2 h-[3px] rounded-full overflow-hidden" style={{ background: 'var(--border)' }}>
                    <div className="h-full rounded-full" style={{ width: `${(total / maxTotal) * 100}%`, background: 'var(--signal)', opacity: 0.6 }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold mb-4">
            <Cpu size={15} className="text-t2" /> 系统资源
          </div>
          <div className="flex flex-col gap-4">
            {[
              { label: 'CPU', value: cpuNow, max: 100, text: cpuNow.toFixed(0) + '%' },
              { label: '内存', value: memPct, max: 100, text: memTotal ? `${fmtBytes(memUsed)} / ${fmtBytes(memTotal)}` : DASH },
              { label: '磁盘', value: sys && sys.disk_total > 0 ? (1 - sys.disk_free / sys.disk_total) * 100 : 0, max: 100,
                text: sys ? `${fmtBytes(sys.disk_free)} 可用` : DASH },
            ].map(row => (
              <div key={row.label}>
                <div className="flex justify-between items-baseline mb-1.5">
                  <span className="text-[12.5px] text-t2">{row.label}</span>
                  <span className="mono text-[12.5px] font-semibold">{row.text}</span>
                </div>
                <MeterLED value={row.value} max={row.max} title={`${row.label} ${row.text}`} />
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2.5 pt-1">
              {[
                ['活跃连接', sys ? String(sys.conn_count) : DASH],
                ['核心', String(sysInfo?.cpu_count ?? DASH)],
                ['版本', sysInfo?.version || DASH],
                ['架构', 'x86'],
              ].map(([k, v]) => (
                <div key={k as string} className="rounded-ctrl bg-[var(--hover)] px-3 py-2">
                  <div className="text-[10.5px] text-t3">{k}</div>
                  <div className="mono text-[12.5px] font-semibold mt-0.5 truncate">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* ⑥ 排行 */}
      <Card className="mb-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2 text-[13.5px] font-semibold">
            <Trophy size={15} className="text-t2" /> 终端流量排行
          </div>
          <Segmented value={rankPeriod} onChange={setRankPeriod} size="sm"
            options={[{ value: 'today', label: '今日' }, { value: '7d', label: '7 天' }, { value: '30d', label: '30 天' }]} />
        </div>
        {ranking.length ? (
          <div className="flex flex-col">
            {(rankOpen ? ranking : ranking.slice(0, 10)).map((r, i) => (
              <div key={r.ip} className="flex items-center gap-3 px-2 py-[7px] rounded-ctrl"
                style={{ background: `color-mix(in srgb, var(--signal) ${Math.max(2, Math.round((r.total / (ranking[0]?.total || 1)) * 12))}%, transparent)` }}>
                <span className="mono text-[12px] font-bold w-6 text-right" style={{ color: i < 3 ? 'var(--signal)' : 'var(--text-3)' }}>{i + 1}</span>
                <span className="mono text-[12.5px] w-32 truncate">{r.ip}</span>
                <span className="mono text-[12px] text-t2 ml-auto shrink-0">↓ {fmtBytes(r.rx)} · ↑ {fmtBytes(r.tx)}</span>
              </div>
            ))}
            {ranking.length > 10 && (
              <button onClick={() => setRankOpen(v => !v)} className="mt-2 text-[12.5px] text-t2 hover:text-t1 cursor-pointer self-center">
                {rankOpen ? '收起' : `展开全部（${ranking.length}）`}
              </button>
            )}
          </div>
        ) : (
          <div className="py-8 text-center text-t3 text-[12.5px]">暂无排行数据（聚合数据按分钟入库，运行一段时间后显示）</div>
        )}
      </Card>

      {/* ⑤ CPU/内存历史 */}
      <Card>
        <div className="flex items-center gap-2 text-[13.5px] font-semibold mb-2">
          <Activity size={15} className="text-t2" /> CPU / 内存历史
          <span className="text-[11px] text-t3 font-normal">CPU 为文字色 · 内存为冰蓝</span>
        </div>
        <div ref={sysChartRef} style={{ height: 200 }} />
      </Card>
    </div>
  )
}
