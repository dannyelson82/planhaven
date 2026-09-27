import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { type ReactNode, useEffect } from 'react'
import { RouterProvider } from 'react-aria-components'
import { api, type Session } from './api.ts'
import { match, navigate, usePath } from './router.ts'
import { AccountScreen } from './screens/Account.tsx'
import { AssetScreen, AssetsScreen } from './screens/Assets.tsx'
import { InviteScreen, LoginScreen, SecondFactorScreen, SetupScreen } from './screens/Auth.tsx'
import { ListScreen } from './screens/Lists.tsx'
import { NoteScreen } from './screens/Notes.tsx'
import { ProjectScreen } from './screens/Project.tsx'
import { ProjectsScreen } from './screens/Projects.tsx'
import { TrashScreen } from './screens/Trash.tsx'
import { useSession } from './session.ts'
import { StepUpProvider } from './stepup.tsx'
import { AuthPage, Button, Link } from './ui.tsx'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000 } } })

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* In-app links change the page without reloading the whole app. */}
      <RouterProvider navigate={navigate}>
        <Root />
      </RouterProvider>
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
  if (session.isError) return <Unreachable retry={() => void session.refetch()} />
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
    case 'list':
      return <ListScreen id={route.id} />
    case 'note':
      return <NoteScreen id={route.id} me={{ id: session.user.id, name: session.user.display_name }} />
    case 'assets':
      return <AssetsScreen />
    case 'asset':
      return <AssetScreen id={route.id} myId={session.user.id} />
    case 'trash':
      return <TrashScreen />
    case 'account':
      return <AccountScreen session={session} />
    default:
      return <p>Page not found. <Link to="/projects" className="text-brand-700">Go to projects</Link></p>
  }
}

/** The app opened (from the phone's home screen, say) but the server can't be reached. */
function Unreachable({ retry }: { retry: () => void }) {
  useEffect(() => {
    window.addEventListener('online', retry)
    return () => window.removeEventListener('online', retry)
  }, [retry])
  return (
    <AuthPage title="Can't reach Planhaven">
      <div className="space-y-4">
        <p>You seem to be offline, or the server isn't answering. This page tries again when you're back online.</p>
        <Button className="w-full" onPress={retry}>Try again</Button>
      </div>
    </AuthPage>
  )
}

const NAV = [
  { to: '/projects', label: 'Projects' },
  { to: '/assets', label: 'Assets' },
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
