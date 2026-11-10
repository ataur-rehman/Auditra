import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api, { tokens } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  const loadMe = useCallback(async () => {
    if (!tokens.access()) { setUser(null); setReady(true); return }
    try {
      const { data } = await api.get('/auth/me/')
      setUser(data)
    } catch {
      setUser(null)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => { loadMe() }, [loadMe])

  const login = useCallback(async (username, password) => {
    const { data } = await api.post('/auth/login/', { username, password })
    tokens.save(data.access, data.refresh)
    const me = await api.get('/auth/me/')
    setUser(me.data)
    return me.data
  }, [])

  const logout = useCallback(async () => {
    try { await api.post('/auth/logout/', { refresh: tokens.refresh() }) } catch { /* token already gone */ }
    tokens.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({
    user, ready, login, logout,
    isAdmin: user?.role === 'admin',
    isEmployee: user?.role === 'employee',
  }), [user, ready, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
