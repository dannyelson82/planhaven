import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api, type Session } from './api.ts'
import { match, usePath } from './router.ts'
import { AccountScreen } from './screens/Account.tsx'
import { InviteScreen, LoginScreen, SecondFactorScreen, SetupScreen } from './screens/Auth.tsx'
import { ProjectScreen } from './screens/Project.tsx'
import { ProjectsScreen } from './screens/Projects.tsx'
import { useSession } from './session.ts'
import { StepUpProvider } from './stepup.tsx'
import { Link } from './ui.tsx'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000 } } })

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  )
}

function Root() {
  const path = usePath()
  const route = match(path)
  const session = useSession()
  const setup = useQuery({
    queryKey: ['setup'],
    queryFn: () => api<{ setup_required: boolean }>('GET', '/api/v1/setup'),
    enabled: session.isSuccess && session.data === null,
  })
  if (route.name === 'invite' && !session.data) return <InviteScreen />
  if (session.isPending) return <p className="p-6 text-stone-500">Loading…</p>
  if (!session.data) {
    if (setup.data?.setup_required) return <SetupScreen />
    return <LoginScreen />
  }
  if (!session.data.mfa_verified) return <SecondFactorScreen />
  return (
    <StepUpProvider>
      <Shell session={session.data}>{screen(route, session.data)}</Shell>
    </StepUpProvider>
  )
}

function screen(route: ReturnType<typeof match>, session: Session): ReactNode {
  switch (route.name) {
    case 'projects':
      return <ProjectsScreen />
    case 'project':
      return <ProjectScreen id={route.id} myId={session.user.id} />
    case 'account':
      return <AccountScreen session={session} />
    default:
      return <p>Page not found. <Link to="/projects" className="text-brand-700">Go to projects</Link></p>
  }
}

const NAV = [
  { to: '/projects', label: 'Projects' },
  { to: '/account', label: 'Account' },
]

/** Phone: content with a bottom tab bar in thumb reach. Desktop: sidebar + content. */
function Shell({ session, children }: { session: Session; children: ReactNode }) {
  const path = usePath()
  const active = (to: string) => path === to || path.startsWith(`${to}/`) || (to === '/projects' && path === '/')
  return (
    <div className="min-h-dvh md:flex">
      <nav aria-label="Main" className="hidden w-56 shrink-0 flex-col gap-1 border-r border-stone-200 p-4 md:flex dark:border-stone-800">
        <p className="mb-4 font-bold text-brand-700 dark:text-brand-100">Planhaven</p>
        {NAV.map((n) => (
          <Link key={n.to} to={n.to} className={`rounded-xl px-3 py-2 ${active(n.to) ? 'bg-brand-100 font-semibold text-brand-700 dark:bg-stone-800 dark:text-brand-100' : ''}`}>
            {n.label}
          </Link>
        ))}
        <p className="mt-auto text-xs text-stone-500">{session.user.display_name}</p>
      </nav>
      <main className="mx-auto w-full max-w-5xl px-4 pb-24 pt-[max(1rem,env(safe-area-inset-top))] md:px-8 md:pb-8">{children}</main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 flex border-t border-stone-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-stone-800 dark:bg-stone-950/95">
        {NAV.map((n) => (
          <Link key={n.to} to={n.to} className={`flex min-h-14 flex-1 items-center justify-center text-sm ${active(n.to) ? 'font-semibold text-brand-700 dark:text-brand-100' : 'text-stone-600 dark:text-stone-400'}`}>
            {n.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}
