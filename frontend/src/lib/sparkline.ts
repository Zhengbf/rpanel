/** 前端环形缓冲：KPI 迷你趋势图用（不改后端） */
export class RingSeries {
  private data: Array<{ t: number; v: number }> = []
  constructor(private maxlen = 600) {}
  push(v: number) {
    this.data.push({ t: Date.now(), v })
    if (this.data.length > this.maxlen) this.data.shift()
  }
  series(): Array<[number, number]> {
    return this.data.map(d => [d.t, d.v])
  }
  last(): number { return this.data.length ? this.data[this.data.length - 1].v : 0 }
}
