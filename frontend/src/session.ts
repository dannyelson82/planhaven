import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, type Session, setCsrfToken } from './api.ts'
import { isOffline, offlineUser, rememberUser, wipeOfflineData } from './offline.ts'

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async (): Promise<Session | null> => {
      try {
        const session = await api<Session>('GET', '/api/v1/auth/session')
        setCsrfToken(session.csrf_token)
        if (session.mfa_verified) void rememberUser(session.user)
        return session
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setCsrfToken(null)
          await wipeOfflineData()
          return null
        }
        // No connection: open with what this device kept, if someone was signed in here.
        const user = isOffline(e) ? await offlineUser() : null
        if (user) return { user, csrf_token: '', mfa_verified: true, offline: true }
        throw e
      }
    },
    retry: false,
    networkMode: 'always',
  })
}

export function useRefreshSession() {
  const client = useQueryClient()
  return async (session?: Session) => {
    if (session) {
      setCsrfToken(session.csrf_token)
      client.setQueryData(['session'], session)
    }
    await client.invalidateQueries()
  }
}
