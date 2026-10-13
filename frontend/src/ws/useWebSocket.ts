import { useEffect, useRef, useCallback } from 'react'

export function useWebSocket(topics: string[], onMessage: (topic: string, data: any) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const cbRef = useRef(onMessage)
  cbRef.current = onMessage
  const topicsKey = topics.join(',')

  const connect = useCallback(() => {
    // 避免重复连接
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return
    const token = localStorage.getItem('access_token') || ''
    // 没登录就不连：否则登录页会每隔几秒撞一次 403
    if (!token) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws`)
    wsRef.current = ws
    ws.onopen = () => {
      retryRef.current = 0
      // 令牌放第一帧，不放 URL（URL 会进服务端访问日志）
      ws.send(JSON.stringify({ token, topics: topicsKey ? topicsKey.split(',') : [] }))
    }
    ws.onmessage = e => {
      try { const m = JSON.parse(e.data); cbRef.current(m.topic, m.data) } catch {}
    }
    ws.onclose = ev => {
      wsRef.current = null
      // 4401 = 未认证或令牌过期：别重连，等下次登录
      if (ev.code === 4401) return
      const delay = Math.min(1000 * 2 ** retryRef.current++, 30000)
      timerRef.current = window.setTimeout(connect, delay)
    }
  }, [topicsKey])

  useEffect(() => {
    connect()
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect])
}
