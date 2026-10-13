/**
 * 终端（一级页面）：内含二级选项卡「设备列表 / 封禁列表」。
 * 新增终端相关功能时，在这里加一个 tab 即可，不必再占用左侧主导航。
 */
import { useNavigate } from 'react-router-dom'
import { MonitorSmartphone, ShieldBan } from 'lucide-react'
import Devices from './Devices'
import Blocked from './Blocked'
import { Segmented } from '../components/ui'

export default function DevicesPage({ tab }: { tab: 'devices' | 'blocked' }) {
  const nav = useNavigate()
  return (
    <div className="animate-in">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2.5">
          <Segmented
            value={tab}
            onChange={v => nav(v === 'devices' ? '/devices' : '/devices/blocked')}
            options={[
              { value: 'devices', label: '设备列表' },
              { value: 'blocked', label: '封禁列表' },
            ]}
          />
        </div>
      </div>
      {tab === 'devices'
        ? <Devices />
        : (
          <div className="flex items-center gap-2 text-[13px] text-t2 mb-3">
            <ShieldBan size={14} /> 被封禁的终端只能访问局域网，无法访问外网
          </div>
        )}
      {tab === 'blocked' && <Blocked />}
    </div>
  )
}
