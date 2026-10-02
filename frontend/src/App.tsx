import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useEffect, useState, useSyncExternalStore } from 'react'
import { RouterProvider } from 'react-aria-components'
import { api, type Session } from './api.ts'
import { flushOutbox } from './offline.ts'
import { match, navigate, usePath } from './router.ts'
import { AccountScreen } from './screens/Account.tsx'
import { AdminScreen } from './screens/Admin.tsx'
import { AssetScreen, AssetsScreen } from './screens/Assets.tsx'
import { ContactScreen, ContactsScreen } from './screens/Contacts.tsx'
import { InviteScreen, LoginScreen, ResetScreen, SecondFactorScreen, SetupScreen, SignOutButton } from './screens/Auth.tsx'
import { ListScreen } from './screens/Lists.tsx'
import { NoteScreen } from './screens/Notes.tsx'
import { ProjectScreen } from './screens/Project.tsx'
import { PurchaseScreen } from './screens/Purchase.tsx'
import { ProjectsScreen } from './screens/Projects.tsx'
import { TemplateScreen, TemplatesScreen } from './screens/Templates.tsx'
import { GuestScreen } from './screens/Share.tsx'
import { ShareLinksScreen } from './screens/ShareLinks.tsx'
import { TrashScreen } from './screens/Trash.tsx'
import { NotificationsScreen } from './screens/Notifications.tsx'
import { ConversationScreen, MessagesScreen } from './screens/Messages.tsx'
import { useMessagesUnread } from './conversations.ts'
import { useLiveMe } from './me.ts'
import { TourHost } from './screens/Tour.tsx'
import { syncTimeZone, useUnread } from './notifications.ts'
import { BellIcon } from './icons.tsx'

const HelpScreen = lazy(() => import('./screens/Help.tsx'))
import { useSession } from './session.ts'
import { StepUpProvider } from './stepup.tsx'
import { AuthPage, Button, Link } from './ui.tsx'

// networkMode 'always': without a connection, requests still run and fail fast (or answer
// from the offline copy, see offline.ts) instead of waiting silently.
const queryClient = new QueryClient({
  defaultOptions: {
    // Reconnecting is handled by useReconnect: queued changes go first, then a refresh.
    queries: { staleTime: 10_000, networkMode: 'always', refetchOnReconnect: false },
    mutations: { networkMode: 'always' },
  },
})

function subscribeOnline(listener: () => void): () => void {
  window.addEventListener('online', listener)
  window.addEventListener('offline', listener)
  return () => {
    window.removeEventListener('online', listener)
    window.removeEventListener('offline', listener)
  }
}

function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true)
}

/** Back online: sign in again quietly (fresh session and CSRF token), send the changes kept
 * on this device, then refresh everything. */
function useReconnect(session: Session) {
  const client = useQueryClient()
  const online = useOnline()
  const [refused, setRefused] = useState<string[]>([])
  useEffect(() => {
    if (!online) return
    if (session.offline) {
      void client.refetchQueries({ queryKey: ['session'] })
      return
    }
    void flushOutbox().then(async (result) => {
      if (result.refused.length) setRefused((r) => [...r, ...result.refused])
      await client.invalidateQueries()
    })
  }, [online, session.offline, client])
  return { online, refused, dismiss: () => setRefused([]) }
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* In-app links change the page without reloading the whole app. */}
      <RouterProvider navigate={(path) => navigate(path)}>
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
  // A reset link works whether or not someone is signed in on this device.
  if (route.name === 'reset') return <ResetScreen />
  // Someone with a share link: no account, their own page (ADR 0015).
  if (route.name === 'share') return <GuestScreen />
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
    case 'cost':
      return <PurchaseScreen id={route.id} />
    case 'note':
      return <NoteScreen id={route.id} />
    case 'assets':
      return <AssetsScreen />
    case 'asset':
      return <AssetScreen id={route.id} myId={session.user.id} />
    case 'contacts':
      return <ContactsScreen />
    case 'suppliers':
      return <ContactsScreen key="suppliers" suppliers />
    case 'notifications':
      return <NotificationsScreen />
    case 'messages':
      return <MessagesScreen myId={session.user.id} />
    case 'conversation':
      return <ConversationScreen key={route.id} id={route.id} myId={session.user.id} />
    case 'contact':
      return <ContactScreen id={route.id} myId={session.user.id} />
    case 'admin':
      return session.user.is_admin ? <AdminScreen myId={session.user.id} /> : <p>Page not found.</p>
    case 'trash':
      return <TrashScreen />
    case 'templates':
      return <TemplatesScreen />
    case 'template':
      return <TemplateScreen id={route.id} myId={session.user.id} />
    case 'help':
      return <Suspense fallback={<p className="text-stone-500">Loading…</p>}><HelpScreen slug={route.slug} /></Suspense>
    case 'project-links':
      return <ShareLinksScreen projectId={route.id} />
    case 'project-trash':
      return <TrashScreen projectId={route.id} />
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
    <AuthPage title="Can't reach PlanHaven">
      <div className="space-y-4">
        <p>You seem to be offline, or the server isn't answering. This page tries again when you're back online.</p>
        <Button className="w-full" onPress={retry}>Try again</Button>
      </div>
    </AuthPage>
  )
}

/** The running version at the bottom of every page (owner request: see at a glance that an
 * update arrived). Signed-in only; the server never tells strangers its version. */
function VersionFooter() {
  const about = useQuery({ queryKey: ['about'], queryFn: () => api<{ version: string }>('GET', '/api/v1/about'), staleTime: 60_000 })
  if (!about.data) return null
  return (
    <p className="mt-8 text-center text-xs text-stone-500">
      PlanHaven {about.data.version} · <Link to="/help" className="underline">Help</Link>
    </p>
  )
}

// The phone's bottom bar has room for four plus the bell: Contacts and Suppliers are on
// Account there (and in the side menu on a computer).
const NAV = [
  { to: '/projects', label: 'Projects' },
  { to: '/assets', label: 'Assets' },
  { to: '/messages', label: 'Messages' },
  { to: '/account', label: 'Account' },
]

/** Phone: content with a bottom tab bar in thumb reach. Desktop: sidebar + content. */
function Shell({ session, children }: { session: Session; children: ReactNode }) {
  const path = usePath()
  const { online, refused, dismiss } = useReconnect(session)
  const active = (to: string) => path === to || path.startsWith(`${to}/`) || (to === '/projects' && path === '/')
  const unread = useUnread()
  const unreadMessages = useMessagesUnread()
  useLiveMe()
  useEffect(() => { void syncTimeZone().catch(() => undefined) }, [])
  const badge = unread > 0 && (
    <span className="rounded-full bg-red-600 px-1.5 text-xs font-semibold leading-5 text-white">{unread > 99 ? '99+' : unread}</span>
  )
  const bellLabel = unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'
  // Messages show their own unread count on their tab.
  const label = (n: { to: string; label: string }) =>
    n.to === '/messages' && unreadMessages > 0 ? `Messages, ${unreadMessages} unread` : undefined
  const dot = (n: { to: string }) => n.to === '/messages' && unreadMessages > 0 && (
    <span aria-hidden className="ml-1 inline-block size-2 rounded-full bg-brand-600 align-middle" />
  )
  return (
    <div className="min-h-dvh md:flex">
      <nav aria-label="Main" className="hidden w-56 shrink-0 flex-col gap-1 border-r border-stone-200 p-4 md:flex dark:border-stone-800">
        <p className="mb-4 font-bold text-brand-700 dark:text-brand-100">PlanHaven</p>
        <Link to="/notifications" aria-label={bellLabel}
          className={`flex items-center gap-2 rounded-xl px-3 py-2 ${active('/notifications') ? 'bg-brand-100 font-semibold text-brand-700 dark:bg-stone-800 dark:text-brand-100' : ''}`}>
          <BellIcon /> Notifications {badge}
        </Link>
        {[...NAV, { to: '/contacts', label: 'Contacts' }, { to: '/suppliers', label: 'Suppliers' }, { to: '/templates', label: 'Templates' }, ...(session.user.is_admin ? [{ to: '/admin', label: 'Admin' }] : []), { to: '/help', label: 'Help' }].map((n) => (
          <Link key={n.to} to={n.to} aria-label={label(n)} className={`rounded-xl px-3 py-2 ${active(n.to) ? 'bg-brand-100 font-semibold text-brand-700 dark:bg-stone-800 dark:text-brand-100' : ''}`}>
            {n.label}{dot(n)}
          </Link>
        ))}
        <p className="mt-auto text-xs text-stone-500">{session.user.display_name}</p>
        <SignOutButton className="justify-start px-3" />
      </nav>
      <main className="mx-auto w-full max-w-5xl px-4 pb-24 pt-[max(1rem,env(safe-area-inset-top))] md:px-8 md:pb-8">
        {(!online || session.offline) && (
          <p role="status" className="mb-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Offline: showing what this device saved. List changes are kept and sent when you're back online.
          </p>
        )}
        {refused.length > 0 && (
          <div role="alert" className="mb-4 space-y-2 rounded-xl bg-red-50 p-3 text-sm text-red-900 dark:bg-red-950 dark:text-red-200">
            <p className="font-medium">Some changes made offline couldn't be saved (the item may have been changed or deleted meanwhile):</p>
            <ul className="list-disc pl-5">{refused.map((r, i) => <li key={i}>{r}</li>)}</ul>
            <Button variant="ghost" onPress={dismiss}>OK</Button>
          </div>
        )}
        {children}
        <TourHost isAdmin={session.user.is_admin} />
        <VersionFooter />
      </main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 flex border-t border-stone-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-stone-800 dark:bg-stone-950/95">
        {NAV.map((n) => (
          <Link key={n.to} to={n.to} aria-label={label(n)} className={`flex min-h-14 flex-1 items-center justify-center text-sm ${active(n.to) ? 'font-semibold text-brand-700 dark:text-brand-100' : 'text-stone-600 dark:text-stone-400'}`}>
            {n.label}{dot(n)}
          </Link>
        ))}
        <Link to="/notifications" aria-label={bellLabel}
          className={`relative flex min-h-14 flex-1 items-center justify-center ${active('/notifications') ? 'text-brand-700 dark:text-brand-100' : 'text-stone-600 dark:text-stone-400'}`}>
          <BellIcon />
          {badge && <span className="absolute left-1/2 top-2 ml-1">{badge}</span>}
        </Link>
      </nav>
    </div>
  )
}
