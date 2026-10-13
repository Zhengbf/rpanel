import { describe, it, expect } from 'vitest'
import { fmtUptime, fmtRate, fmtBytes, parseDuration, fmtDuration } from './format'

describe('fmtUptime', () => {
  it('18w4d3h45m -> 130天3小时45分钟', () => {
    expect(fmtUptime('18w4d3h45m')).toBe('130天3小时45分钟')
  })
  it('2w3d4h19m9s -> 17天4小时19分钟（>1天无秒）', () => {
    expect(fmtUptime('2w3d4h19m9s')).toBe('17天4小时19分钟')
  })
  it('5s -> 5秒', () => { expect(fmtUptime('5s')).toBe('5秒') })
  it('3h12m -> 3小时12分钟', () => { expect(fmtUptime('3h12m')).toBe('3小时12分钟') })
  it('空 -> —', () => { expect(fmtUptime('')).toBe('—'); expect(fmtUptime(null)).toBe('—') })
})

describe('fmtRate', () => {
  it('0 -> 0 B/s', () => { expect(fmtRate(0)).toBe('0 B/s') })
  it('1.5e6 -> 1.5 MB/s', () => { expect(fmtRate(1.5e6)).toBe('1.5 MB/s') })
})

describe('fmtBytes', () => {
  it('2.135e9 -> 2.13 GB', () => { expect(fmtBytes(2.135e9)).toBe('2.13 GB') })
})

describe('parseDuration', () => {
  it('never -> -1', () => { expect(parseDuration('never')).toBe(-1) })
  it('1h2m3s -> 3723', () => { expect(parseDuration('1h2m3s')).toBe(3723) })
})

describe('fmtDuration', () => {
  it('3723 -> 1小时2分钟', () => { expect(fmtDuration(3723)).toBe('1小时2分钟') })
  it('90061 -> 1天1小时', () => { expect(fmtDuration(90061)).toBe('1天1小时') })
  it('-1 -> 未知', () => { expect(fmtDuration(-1)).toBe('未知') })
})
