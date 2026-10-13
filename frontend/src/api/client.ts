import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('access_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

/**
 * 401 自动续期。
 *
 * access token 只有 30 分钟有效期。之前收到 401 直接清空登录态跳登录页，
 * 于是用户在面板里用满 30 分钟后，任何写操作（封禁、改 DHCP、绑定静态…）
 * 都会被踢回登录页且操作不生效。现在先用 refresh token 换新令牌并重试原请求，
 * 只有刷新也失败时才真正退出登录。
 */
let refreshing: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return null
  try {
    const { data } = await axios.post('/api/auth/refresh', { refresh_token: refresh })
    localStorage.setItem('access_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
    return data.access_token as string
  } catch {
    return null
  }
}

api.interceptors.response.use(
  r => r,
  async err => {
    const original = err.config as any
    const status = err.response?.status
    if (status !== 401 || original?._retried) return Promise.reject(err)

    original._retried = true
    refreshing = refreshing || refreshAccessToken()
    const token = await refreshing
    refreshing = null

    if (!token) {
      localStorage.clear()
      window.location.href = '/login'
      return Promise.reject(err)
    }
    original.headers = { ...(original.headers || {}), Authorization: `Bearer ${token}` }
    return api.request(original)
  },
)

// 是否已绑定设备
export async function checkBound(): Promise<boolean> {
  try {
    await api.get('/wizard/devices')
    return true
  } catch (e: any) {
    if (e.response?.status === 428 || e.response?.status === 403) return false
    return true // 其他错误不代表未绑定
  }
}

export { api }
export default api
