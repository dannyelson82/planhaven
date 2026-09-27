import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, type Session, setCsrfToken } from './api.ts'

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: async (): Promise<Session | null> => {
      try {
        const session = await api<Session>('GET', '/api/v1/auth/session')
        setCsrfToken(session.csrf_token)
        return session
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setCsrfToken(null)
          return null
        }
        throw e
      }
    },
    retry: false,
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
