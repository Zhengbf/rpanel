/**
 * 网络（一级页面）：二级选项卡容器。
 *
 * 目前只有 DHCP 一个子页；后续加静态路由、端口映射、防火墙、DNS 等功能时，
 * 只需要在 TABS 里加一项 + 写一个子组件，左侧导航不必再动。
 */
import { useNavigate, useParams } from 'react-router-dom'
import { Network as NetworkIcon, Route, Waypoints } from 'lucide-react'
import NetworkDhcp from './NetworkDhcp'
import PortForward from './PortForward'
import NetworkFirewall from './NetworkFirewall'
import { Segmented, EmptyState } from '../components/ui'

const TABS = [
  { key: 'dhcp', label: 'DHCP' },
  { key: 'port-forward', label: '端口转发' },
  { key: 'firewall', label: '防火墙' },
  { key: 'planned', label: '更多功能' },
] as const

/** 规划中的网络功能，先把位置留出来，避免以后导航膨胀 */
const PLANNED = [
  { icon: Route, title: '静态路由', desc: '查看与维护 /ip route，含默认路由与多 WAN 策略' },
  { icon: Waypoints, title: '端口映射', desc: '查看与维护 dst-nat 规则，一键暴露内网服务' },
]

export default function NetworkPage() {
  const nav = useNavigate()
  const params = useParams()
  const rawTab = params.tab as string
  const tab = rawTab === 'port-forward' || rawTab === 'firewall' || rawTab === 'planned'
    ? rawTab
    : 'dhcp'

  return (
    <div className="animate-in">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2.5">
          <NetworkIcon size={16} className="text-t2" />
          <Segmented
            value={tab}
            onChange={v => nav(v === 'dhcp' ? '/network' : `/network/${v}`)}
            options={TABS.map(t => ({ value: t.key, label: t.label }))}
          />
        </div>
      </div>

      {tab === 'dhcp'
        ? <NetworkDhcp />
        : tab === 'port-forward'
          ? <PortForward />
          : tab === 'firewall'
            ? <NetworkFirewall />
          : (
          <div className="card p-6">
            <div className="text-[14px] font-semibold mb-1">规划中的网络功能</div>
            <p className="text-[12.5px] text-t2 mb-5">
              这一页已经预留好位置，新增功能只需要加一个子选项卡，不会让左侧导航变臃肿。
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {PLANNED.map(p => (
                <div key={p.title} className="rounded-ctrl border border-[var(--border)] px-4 py-3.5">
                  <div className="flex items-center gap-2 text-[13px] font-medium mb-1">
                    <p.icon size={14} className="text-t3" /> {p.title}
                  </div>
                  <div className="text-[12px] text-t3 leading-relaxed">{p.desc}</div>
                </div>
              ))}
            </div>
            <EmptyState icon={<NetworkIcon size={20} />} title="以上功能尚未实现"
              desc="需要哪个先做，告诉开发者即可按现有分层快速接入" />
          </div>
        )}
    </div>
  )
}
