// The welcome tour on first sign-in, and "What's new" after an update (maintainer request,
// 2026-10-02): step-by-step popups with pictures from the user guide and "Set it up now"
// buttons. Each shows once per person (the server remembers); both reopen from Help.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useEffect, useState } from 'react'
import { Dialog, Heading, Modal } from 'react-aria-components'
import { api } from '../api.ts'
import { pushState, type PushState, turnOn } from '../push.ts'
import { navigate } from '../router.ts'
import { Button, ErrorText } from '../ui.tsx'
import { type Action, isNewAccount, type Item, LATEST, openTour, RELEASES, unseen, useOpenTour } from '../whatsnew.ts'

type State = { welcome_done: boolean; whats_new_seen: string | null; member_since: string | null }

const SHOTS = import.meta.glob('../../../docs/user-guide/screens/*/*.jpg', { query: '?url', import: 'default', eager: true }) as Record<string, string>

function Shot({ name, alt }: { name: string; alt: string }) {
  const phone = SHOTS[`../../../docs/user-guide/screens/phone/${name}.jpg`]
  const desktop = SHOTS[`../../../docs/user-guide/screens/desktop/${name}.jpg`]
  const cls = 'max-h-56 w-auto rounded-xl ring-1 ring-stone-200 dark:ring-stone-800'
  return (
    <div className="flex justify-center">
      {phone && <img src={phone} alt={alt} className={`${cls} ${desktop ? 'md:hidden' : ''}`} />}
      {desktop && <img src={desktop} alt={alt} className={`${cls} ${phone ? 'hidden md:block' : ''}`} />}
    </div>
  )
}

type Step = { title: string; text: string; shot?: string; action?: Action; admin?: boolean; steps?: string[] }

const WELCOME: Step[] = [
  {
    title: 'Welcome to PlanHaven',
    text: 'Projects for your home, vehicles, boat and more: tasks, shopping and parts lists, notes, photos, quotes and costs, in one place, shared with the people you choose. This short tour shows the basics.',
    shot: 'projects',
  },
  {
    title: 'Put it on your phone',
    text: 'PlanHaven works like an app when it\'s on your Home Screen, and phone alerts need that on an iPhone.',
    action: 'home-screen',
  },
  {
    title: 'Alerts on your phone',
    text: 'Be told when something is due, shared with you or when someone messages you, even when PlanHaven is closed.',
    action: 'push',
  },
  {
    title: 'Start a project',
    text: 'A project is anything you want to get done. On a project, the add bar at the top adds tasks, lists, notes, photos, quotes and costs. Tap a task or a list item to see its details.',
    shot: 'add-bar',
    steps: ['Tap Projects.', 'Type a name under New project and tap Add.', 'Use the add bar to add tasks and lists.'],
    action: 'projects',
  },
  {
    title: 'Messages',
    text: 'Write to anyone on your PlanHaven, one to one or in a group. A green dot shows who\'s online.',
    shot: 'messages',
    action: 'messages',
  },
  {
    title: 'Invite your household',
    text: 'As an admin, you invite people: make an invite link and send it to them. They choose their own password and second factor.',
    action: 'invite',
    admin: true,
  },
  {
    title: 'Keep it safe',
    text: 'Back up your server\'s /config and /data folders, and keep your recovery codes somewhere safe. The admin page of the guide has the details.',
    admin: true,
  },
  {
    title: 'Help is always there',
    text: 'Help (in the menu on a computer, at the bottom of every page on a phone) explains every part of PlanHaven, with pictures for phones and computers. You can take this tour again from there.',
  },
]

/** Shows the welcome tour or "What's new" when due, or when opened from Help. */
export function TourHost({ isAdmin }: { isAdmin: boolean }) {
  const client = useQueryClient()
  const state = useQuery({ queryKey: ['onboarding'], queryFn: () => api<State>('GET', '/api/v1/onboarding'), staleTime: Infinity })
  const opened = useOpenTour()
  const save = useMutation({
    mutationFn: (body: Partial<State>) => api<State>('PUT', '/api/v1/onboarding', body),
    onSuccess: (s) => client.setQueryData(['onboarding'], s),
  })
  if (!state.data) return null
  const s = state.data
  const pending = unseen(s.whats_new_seen, s.member_since)
  // Finishing (or skipping) the tour: old news isn't news to someone just starting; someone
  // who's used PlanHaven before then sees everything new since they joined.
  const doneWelcome = () => {
    openTour(null)
    save.mutate(isNewAccount(s.member_since) ? { welcome_done: true, whats_new_seen: LATEST } : { welcome_done: true })
  }
  const doneNews = () => { openTour(null); save.mutate({ whats_new_seen: LATEST }) }
  if (opened === 'welcome' || (opened === null && !s.welcome_done)) {
    return <WelcomeTour steps={WELCOME.filter((x) => isAdmin || !x.admin)} onDone={doneWelcome} />
  }
  if (opened === 'whats-new') return <WhatsNew releases={RELEASES} onDone={doneNews} all />
  if (opened === null && pending.length > 0) return <WhatsNew releases={pending} onDone={doneNews} />
  return null
}

function Popup({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  return (
    <Modal isOpen isDismissable onOpenChange={(o) => { if (!o) onClose() }}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <Dialog aria-label={label} className="max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-5 outline-none dark:bg-stone-900">
        {children}
      </Dialog>
    </Modal>
  )
}

function WelcomeTour({ steps, onDone }: { steps: Step[]; onDone: () => void }) {
  const [i, setI] = useState(0)
  const step = steps[i]
  const last = i === steps.length - 1
  return (
    <Popup label="Welcome tour" onClose={onDone}>
      <div className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-wide text-stone-500">Step {i + 1} of {steps.length}</p>
        <Heading slot="title" className="text-xl font-bold">{step.title}</Heading>
        <p className="text-stone-700 dark:text-stone-300">{step.text}</p>
        {step.shot && <Shot name={step.shot} alt={step.title} />}
        {step.steps && <ol className="list-decimal space-y-1 pl-5 text-sm">{step.steps.map((t) => <li key={t}>{t}</li>)}</ol>}
        {step.action && <ActionArea action={step.action} onLeave={onDone} />}
        <div className="flex items-center justify-between gap-2 pt-2">
          {last ? <span /> : <Button variant="ghost" onPress={onDone}>Skip the tour</Button>}
          <div className="flex gap-2">
            {i > 0 && <Button variant="secondary" onPress={() => setI(i - 1)}>Back</Button>}
            <Button onPress={() => (last ? onDone() : setI(i + 1))}>{last ? 'Done' : 'Next'}</Button>
          </div>
        </div>
      </div>
    </Popup>
  )
}

function WhatsNew({ releases, onDone, all = false }: { releases: typeof RELEASES; onDone: () => void; all?: boolean }) {
  const items = releases.flatMap((r) => r.items.map((item) => ({ item, version: r.version })))
  const [i, setI] = useState(0)
  const { item, version } = items[i]
  const last = i === items.length - 1
  return (
    <Popup label="What's new" onClose={onDone}>
      <div className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-wide text-stone-500">
          What's new{all ? '' : ` since you last looked`} · {i + 1} of {items.length} · version {version}
        </p>
        <Heading slot="title" className="text-xl font-bold">{item.title}</Heading>
        <ItemBody item={item} onLeave={onDone} />
        <div className="flex items-center justify-between gap-2 pt-2">
          {last ? <span /> : <Button variant="ghost" onPress={onDone}>Close</Button>}
          <div className="flex gap-2">
            {i > 0 && <Button variant="secondary" onPress={() => setI(i - 1)}>Back</Button>}
            <Button onPress={() => (last ? onDone() : setI(i + 1))}>{last ? 'Got it' : 'Next'}</Button>
          </div>
        </div>
      </div>
    </Popup>
  )
}

function ItemBody({ item, onLeave }: { item: Item; onLeave: () => void }) {
  return (
    <>
      <p className="text-stone-700 dark:text-stone-300">{item.text}</p>
      {item.shot && <Shot name={item.shot} alt={item.title} />}
      {item.steps && (
        <div>
          <p className="text-sm font-medium">How to</p>
          <ol className="list-decimal space-y-1 pl-5 text-sm">{item.steps.map((t) => <li key={t}>{t}</li>)}</ol>
        </div>
      )}
      {item.action && <ActionArea action={item.action} onLeave={onLeave} />}
      {item.guide && (
        <Button variant="ghost" className="-ml-2 px-2 text-sm text-brand-700 dark:text-brand-100"
          onPress={() => { onLeave(); navigate(item.guide === 'README' ? '/help' : `/help/${item.guide}`) }}>More in Help</Button>
      )}
    </>
  )
}

const GO: Partial<Record<Action, { label: string; to: string }>> = {
  projects: { label: 'Go to Projects', to: '/projects' },
  chores: { label: 'Open Chores', to: '/chores' },
  messages: { label: 'Open Messages', to: '/messages' },
  invite: { label: 'Invite someone', to: '/admin' },
  suppliers: { label: 'Open Suppliers', to: '/suppliers' },
  assets: { label: 'Open Assets', to: '/assets' },
  'notification-settings': { label: 'Choose in Account', to: '/account' },
  presence: { label: 'Choose in Account', to: '/account' },
}

/** "Set it up now": done right here where possible, otherwise a button to the place. */
function ActionArea({ action, onLeave }: { action: Action; onLeave: () => void }) {
  if (action === 'push') return <PushSetup />
  if (action === 'home-screen') return <HomeScreen />
  const go = GO[action]
  if (!go) return null
  return <Button variant="secondary" onPress={() => { onLeave(); navigate(go.to) }}>{go.label}</Button>
}

function PushSetup() {
  const [state, setState] = useState<PushState | null>(null)
  useEffect(() => { void pushState().then(setState) }, [])
  const on = useMutation({ mutationFn: turnOn, onSettled: async () => setState(await pushState()) })
  if (state === 'on') return <p className="rounded-xl bg-brand-50 p-3 text-sm dark:bg-stone-800">Phone alerts are on for this device.</p>
  if (state === 'needs-home-screen') return <p className="rounded-xl bg-stone-100 p-3 text-sm dark:bg-stone-800">On an iPhone, add PlanHaven to the Home Screen first (the step before), open it from there, then turn alerts on in Account.</p>
  if (state === 'blocked') return <p className="rounded-xl bg-stone-100 p-3 text-sm dark:bg-stone-800">Alerts are blocked for PlanHaven in this device's settings. Allow them there, then turn them on in Account.</p>
  if (state === 'unsupported') return <p className="rounded-xl bg-stone-100 p-3 text-sm dark:bg-stone-800">This browser can't get alerts. You'll still see everything under the bell.</p>
  return (
    <div className="space-y-2">
      <Button onPress={() => on.mutate()} isDisabled={on.isPending || state === null}>Turn on phone alerts</Button>
      <ErrorText error={on.error} />
    </div>
  )
}

function HomeScreen() {
  const standalone = window.matchMedia('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true
  if (standalone) return <p className="rounded-xl bg-brand-50 p-3 text-sm dark:bg-stone-800">You're using PlanHaven from your Home Screen.</p>
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent)
  return (
    <ol className="list-decimal space-y-1 rounded-xl bg-stone-100 p-3 pl-8 text-sm dark:bg-stone-800">
      {ios ? (
        <>
          <li>In Safari, tap the Share button.</li>
          <li>Tap Add to Home Screen, then Add.</li>
          <li>Open PlanHaven from the new icon.</li>
        </>
      ) : (
        <>
          <li>Open the browser's menu (⋮).</li>
          <li>Tap Install app or Add to Home screen.</li>
          <li>Open PlanHaven from the new icon. (On a computer, the install button is in the address bar.)</li>
        </>
      )}
    </ol>
  )
}
