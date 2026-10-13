/**
 * ECharts 按需引入：只带折线，省掉地图/3D 等未用模块。
 * 主题色取 CSS 变量（随 data-theme 切换）。
 */
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

export function readVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

export function chartTheme() {
  return {
    text: readVar('--text-2'),
    grid: readVar('--border'),
    signal: readVar('--signal'),
    ice: readVar('--ice'),
    danger: readVar('--danger'),
    card: readVar('--card'),
  }
}

export { echarts }
