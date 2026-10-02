// Notifications (ADR 0018): the list behind the bell, and the settings in Account: what you're
// told about and where, quiet hours, and phone alerts on this device.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api.ts'
import type { Notice } from '../notifications.ts'
import { pushState, type PushState, turnOff, turnOn } from '../push.ts'
import { navigate } from '../router.ts'
import { Button, Card, ErrorText } from '../ui.tsx'

const when = (iso: string) => {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function NotificationsScreen() {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ['notifications', 'list'], queryFn: () => api<Notice[]>('GET', '/api/v1/notifications'), staleTime: 0 })
  const refresh = () => client.invalidateQueries({ queryKey: ['notifications'] })
  const readAll = useMutation({ mutationFn: () => api('POST', '/api/v1/notifications/read-all'), onSettled: refresh })
  const open = async (n: Notice) => {
    if (!n.read) await api('POST', `/api/v1/notifications/${n.id}/read`).catch(() => undefined)
    await refresh()
    navigate(n.url.startsWith('/') ? n.url : '/notifications')
  }
  const items = list.data ?? []
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Notifications</h1>
        {items.some((n) => !n.read) && <Button variant="secondary" onPress={() => readAll.mutate()} isDisabled={readAll.isPending}>Mark all read</Button>}
      </div>
      {list.isSuccess && items.length === 0 && <p className="text-stone-500">Nothing yet. You'll be told here when something needs you.</p>}
      <ul aria-label="Notifications" className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
        {items.map((n) => (
          <li key={n.id}>
            <button type="button" onClick={() => void open(n)}
              className="flex min-h-14 w-full items-start gap-3 px-3 py-3 text-left hover:bg-stone-50 focus-visible:outline-2 focus-visible:outline-brand-600 dark:hover:bg-stone-800">
              <span aria-hidden className={`mt-2 size-2.5 shrink-0 rounded-full ${n.read ? '' : 'bg-brand-600'}`} />
              <span className="min-w-0 flex-1">
                <span className={`block ${n.read ? '' : 'font-semibold'}`}>{n.title}{!n.read && <span className="sr-only"> (unread)</span>}</span>
                {n.body && <span className="block text-sm text-stone-500">{n.body}</span>}
              </span>
              <span className="shrink-0 text-xs text-stone-500">{when(n.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-sm text-stone-500">Choose what you're told about, and quiet hours, in Account.</p>
      <ErrorText error={list.error ?? readAll.error} />
    </div>
  )
}

type Choice = 'push' | 'app' | 'off'
type Group = 'shared' | 'tasks' | 'service' | 'share_links' | 'security'
type Settings = { prefs: Record<Group, Choice>; quiet_from: string | null; quiet_to: string | null; time_zone: string; previews: boolean }
type Device = { id: string; label: string; created_at: string; last_success_at: string | null }

const GROUP_LABEL: Record<Group, string> = {
  shared: 'Shared with you',
  tasks: 'Tasks due today and overdue',
  service: 'Asset services due',
  share_links: 'Someone used your share link',
  security: 'Sign-ins and security changes',
}
const CHOICE_LABEL: Record<Choice, string> = { push: 'On the phone and in the app', app: 'In the app only', off: 'Off' }
const hhmm = (t: string | null) => (t ? t.slice(0, 5) : '')
const select = 'mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900'

/** Account: what you're told about, quiet hours, and phone alerts on this device. */
export function NotificationSettingsCard() {
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['notification-settings'], queryFn: () => api<Settings>('GET', '/api/v1/notification-settings') })
  const save = useMutation({
    mutationFn: (next: Settings) => api<Settings>('PUT', '/api/v1/notification-settings', {
      ...next, time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    }),
    // Shown at once (a checkbox or menu that waits for the server looks like it didn't take).
    onMutate: (next) => {
      const before = client.getQueryData<Settings>(['notification-settings'])
      client.setQueryData(['notification-settings'], next)
      return before
    },
    onError: (_e, _next, before) => client.setQueryData(['notification-settings'], before),
    onSuccess: (s) => client.setQueryData(['notification-settings'], s),
  })
  const s = settings.data
  const [quiet, setQuiet] = useState<{ from: string; to: string } | null>(null)
  const shownQuiet = quiet ?? { from: hhmm(s?.quiet_from ?? null), to: hhmm(s?.quiet_to ?? null) }
  // The box shows the change at once; the saved setting takes over when it comes back.
  const saved = Boolean(s?.quiet_from)
  const [quietBox, setQuietBox] = useState<{ saved: boolean; on: boolean } | null>(null)
  const quietOn = quietBox && quietBox.saved === saved ? quietBox.on : saved
  return (
    <section aria-label="Notifications settings">
      <Card className="space-y-4">
        <h2 className="font-semibold">Notifications</h2>
        <PhoneAlerts />
        {s && (
          <>
            <div className="space-y-3">
              {(Object.keys(GROUP_LABEL) as Group[]).map((g) => (
                <label key={g} className="block text-sm font-medium">
                  {GROUP_LABEL[g]}
                  <select value={s.prefs[g]} className={select}
                    onChange={(e) => save.mutate({ ...s, prefs: { ...s.prefs, [g]: e.target.value as Choice } })}>
                    {(Object.keys(CHOICE_LABEL) as Choice[]).filter((c) => g !== 'security' || c !== 'off').map((c) => <option key={c} value={c}>{CHOICE_LABEL[c]}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Quiet hours</legend>
              <p className="text-sm text-stone-500">No phone alerts in these hours; they come when quiet hours end. They still show in the app.</p>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input type="checkbox" className="size-5 accent-brand-600" checked={quietOn}
                  onChange={(e) => {
                    const on = e.target.checked
                    setQuietBox({ saved, on })
                    save.mutate({ ...s, quiet_from: on ? '22:00' : null, quiet_to: on ? '07:00' : null })
                  }} />
                Quiet hours on
              </label>
              {quietOn && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="text-sm font-medium">From
                    <input type="time" required value={shownQuiet.from} className={select}
                      onChange={(e) => setQuiet({ ...shownQuiet, from: e.target.value })} />
                  </label>
                  <label className="text-sm font-medium">To
                    <input type="time" required value={shownQuiet.to} className={select}
                      onChange={(e) => setQuiet({ ...shownQuiet, to: e.target.value })} />
                  </label>
                  <Button variant="secondary" isDisabled={!quiet || !quiet.from || !quiet.to || save.isPending}
                    onPress={() => { if (quiet) save.mutate({ ...s, quiet_from: quiet.from, quiet_to: quiet.to }, { onSuccess: () => setQuiet(null) }) }}>
                    Save quiet hours
                  </Button>
                </div>
              )}
            </fieldset>
          </>
        )}
        <ErrorText error={settings.error ?? save.error} />
      </Card>
    </section>
  )
}

function PhoneAlerts() {
  const client = useQueryClient()
  const [state, setState] = useState<PushState | null>(null)
  useEffect(() => { void pushState().then(setState) }, [])
  const devices = useQuery({ queryKey: ['push-devices'], queryFn: () => api<Device[]>('GET', '/api/v1/push/devices') })
  const done = async () => { setState(await pushState()); await client.invalidateQueries({ queryKey: ['push-devices'] }) }
  const on = useMutation({ mutationFn: turnOn, onSettled: done })
  const off = useMutation({ mutationFn: turnOff, onSettled: done })
  const test = useMutation({ mutationFn: () => api('POST', '/api/v1/push/test') })
  const remove = useMutation({ mutationFn: (id: string) => api('DELETE', `/api/v1/push/devices/${id}`), onSettled: done })
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Phone alerts on this device</p>
      {state === 'needs-home-screen' && (
        <p className="text-sm text-stone-600 dark:text-stone-400">
          On an iPhone, add PlanHaven to the Home Screen first (Share, then Add to Home Screen), open it from there, and come back here.
        </p>
      )}
      {state === 'unsupported' && <p className="text-sm text-stone-600 dark:text-stone-400">This browser can't get phone alerts.</p>}
      {state === 'blocked' && <p className="text-sm text-stone-600 dark:text-stone-400">Alerts are blocked for PlanHaven in this device's settings. Allow them there, then come back.</p>}
      <div className="flex flex-wrap gap-2">
        {state === 'off' && <Button onPress={() => on.mutate()} isDisabled={on.isPending}>Turn on phone alerts</Button>}
        {state === 'on' && (
          <>
            <Button variant="secondary" onPress={() => test.mutate()} isDisabled={test.isPending}>{test.isSuccess ? 'Test sent' : 'Send a test'}</Button>
            <Button variant="ghost" onPress={() => off.mutate()} isDisabled={off.isPending}>Turn off on this device</Button>
          </>
        )}
      </div>
      {(devices.data ?? []).length > 0 && (
        <ul aria-label="Devices with phone alerts" className="space-y-1 text-sm">
          {(devices.data ?? []).map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate">{d.label || 'Device'} · since {new Date(d.created_at).toLocaleDateString()}</span>
              <Button variant="ghost" aria-label={`Stop alerts on ${d.label || 'device'}`} onPress={() => remove.mutate(d.id)}>✕</Button>
            </li>
          ))}
        </ul>
      )}
      <ErrorText error={on.error ?? off.error ?? test.error ?? remove.error} />
    </div>
  )
}
