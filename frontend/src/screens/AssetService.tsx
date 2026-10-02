// Keeping an asset serviced (maintainer's testing notes, 2026-10-02): meter readings (distance
// and hours), maintenance schedules from the manufacturer's manual, and the service history.
// What's due is worked out by the server from the last service and the highest readings.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api.ts'
import { formatCents, parseAmount } from '../money.ts'
import { Button, Card, ErrorText, Field, Form } from '../ui.tsx'

type Status = 'overdue' | 'soon' | 'ok' | 'unknown'
type Schedule = {
  id: string; name: string; every_distance: string | null; every_hours: string | null; every_months: number | null
  notes: string; version: number; last_done_on: string | null; status: Status
  due_on: string | null; due_distance: string | null; due_hours: string | null
}
type ServiceRecord = {
  id: string; schedule_id: string | null; title: string; done_on: string; distance: string | null
  hours: string | null; cost_cents: number | null; notes: string
}
type Reading = { id: string; read_on: string; distance: string | null; hours: string | null }
type Service = {
  distance_unit: 'km' | 'mi'; distance: string | null; hours: string | null
  readings: Reading[]; schedules: Schedule[]; records: ServiceRecord[]; can_edit: boolean
}

const STATUS: { [s in Status]: { label: string; className: string } } = {
  overdue: { label: 'Overdue', className: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' },
  soon: { label: 'Due soon', className: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200' },
  ok: { label: 'OK', className: 'bg-brand-100 text-brand-700 dark:bg-stone-800 dark:text-brand-100' },
  unknown: { label: 'Not recorded yet', className: 'bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300' },
}
const today = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD, this device's day
const num = (v: string | null) => (v === null ? '' : Number(v).toLocaleString())
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
const clean = (v: string) => v.trim().replace(/[\s,]/g, '')
const isNumber = (v: string) => !clean(v) || /^\d+(\.\d)?$/.test(clean(v))
const orNull = (v: string) => (clean(v) ? clean(v) : null)

function every(s: Schedule, unit: string): string {
  const parts = [
    s.every_distance && `${num(s.every_distance)} ${unit}`,
    s.every_hours && `${num(s.every_hours)} hours`,
    s.every_months && (s.every_months === 1 ? '1 month' : `${s.every_months} months`),
  ].filter(Boolean)
  return `Every ${parts.join(' or ')}${parts.length > 1 ? ', whichever comes first' : ''}`
}

function nextDue(s: Schedule, unit: string): string | null {
  const parts = [
    s.due_on && day(s.due_on),
    s.due_distance && `${num(s.due_distance)} ${unit}`,
    s.due_hours && `${num(s.due_hours)} hours`,
  ].filter(Boolean)
  return parts.length ? `Next: ${parts.join(' or ')}` : null
}

export function AssetService({ assetId }: { assetId: string }) {
  const key = ['asset-service', assetId]
  const service = useQuery({ queryKey: key, queryFn: () => api<Service>('GET', `/api/v1/assets/${assetId}/service`) })
  const [adding, setAdding] = useState<'reading' | 'schedule' | 'record' | null>(null)
  const [doneFor, setDoneFor] = useState<Schedule | null>(null)
  if (service.error) return <ErrorText error={service.error} />
  if (!service.data) return null
  const s = service.data
  const unit = s.distance_unit
  const toggle = (what: typeof adding) => { setDoneFor(null); setAdding(adding === what ? null : what) }
  return (
    <section aria-label="Service" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Service</h2>
        {s.can_edit && <UnitPicker assetId={assetId} unit={unit} />}
      </div>
      <p className="text-stone-600 dark:text-stone-400">
        {s.distance || s.hours
          ? `Now: ${[s.distance && `${num(s.distance)} ${unit}`, s.hours && `${num(s.hours)} hours`].filter(Boolean).join(' · ')}`
          : 'No readings yet.'}
      </p>
      {s.can_edit && (
        <div className="flex flex-wrap gap-2">
          <Button variant={adding === 'reading' ? 'primary' : 'secondary'} onPress={() => toggle('reading')}>+ Reading</Button>
          <Button variant={adding === 'schedule' ? 'primary' : 'secondary'} onPress={() => toggle('schedule')}>+ Schedule</Button>
          <Button variant={adding === 'record' ? 'primary' : 'secondary'} onPress={() => toggle('record')}>+ Service done</Button>
        </div>
      )}
      {adding === 'reading' && <ReadingForm assetId={assetId} unit={unit} onDone={() => setAdding(null)} />}
      {adding === 'schedule' && <ScheduleForm assetId={assetId} unit={unit} onDone={() => setAdding(null)} />}
      {(adding === 'record' || doneFor) && (
        <RecordForm key={doneFor?.id ?? 'any'} assetId={assetId} unit={unit} service={s} schedule={doneFor}
          onDone={() => { setAdding(null); setDoneFor(null) }} />
      )}

      {s.schedules.length > 0 && (
        <ul className="space-y-2" aria-label="Maintenance schedules">
          {s.schedules.map((x) => (
            <li key={x.id}>
              <ScheduleCard assetId={assetId} schedule={x} unit={unit} canEdit={s.can_edit}
                onDone={() => { setAdding(null); setDoneFor(x) }} />
            </li>
          ))}
        </ul>
      )}
      {s.schedules.length === 0 && (
        <p className="text-sm text-stone-500">
          No maintenance schedules yet. Add the ones from the owner's manual with <strong>+ Schedule</strong>, for example "Engine oil, every 8,000 km or 12 months".
        </p>
      )}
      <History assetId={assetId} service={s} />
    </section>
  )
}

function UnitPicker({ assetId, unit }: { assetId: string; unit: 'km' | 'mi' }) {
  const client = useQueryClient()
  const set = useMutation({
    mutationFn: (next: string) => api('PUT', `/api/v1/assets/${assetId}/distance-unit`, { unit: next }),
    onSettled: () => client.invalidateQueries({ queryKey: ['asset-service', assetId] }),
  })
  return (
    <label className="flex items-center gap-2 text-sm">
      Distance in
      <select value={unit} onChange={(e) => set.mutate(e.target.value)} disabled={set.isPending}
        className="min-h-11 rounded-xl border border-stone-300 bg-white px-2 dark:border-stone-700 dark:bg-stone-900">
        <option value="km">km</option>
        <option value="mi">miles</option>
      </select>
    </label>
  )
}

function useRefresh(assetId: string) {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: ['asset-service', assetId] })
}

function ReadingForm({ assetId, unit, onDone }: { assetId: string; unit: string; onDone: () => void }) {
  const refresh = useRefresh(assetId)
  const [on, setOn] = useState(today())
  const [distance, setDistance] = useState('')
  const [hours, setHours] = useState('')
  const ok = isNumber(distance) && isNumber(hours) && (clean(distance) || clean(hours))
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/assets/${assetId}/readings`, { read_on: on, distance: orNull(distance), hours: orNull(hours) }),
    onSuccess: async () => { await refresh(); onDone() },
  })
  return (
    <Card>
      <Form onSubmit={(e) => { e.preventDefault(); if (ok) add.mutate() }}>
        <h3 className="font-semibold">New reading</h3>
        <DateField label="Date" value={on} onChange={setOn} />
        <div className="flex gap-2">
          <div className="min-w-0 flex-1"><Field label={unit === 'mi' ? 'Odometer (miles)' : 'Odometer (km)'} inputMode="decimal" maxLength={12} value={distance} onChange={setDistance} isInvalid={!isNumber(distance)} /></div>
          <div className="min-w-0 flex-1"><Field label="Hours" inputMode="decimal" maxLength={10} value={hours} onChange={setHours} isInvalid={!isNumber(hours)} /></div>
        </div>
        <ErrorText error={add.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!ok || add.isPending}>Save reading</Button>
          <Button variant="ghost" onPress={onDone}>Cancel</Button>
        </div>
      </Form>
    </Card>
  )
}

function ScheduleForm({ assetId, unit, schedule, onDone }: { assetId: string; unit: string; schedule?: Schedule; onDone: () => void }) {
  const refresh = useRefresh(assetId)
  const [name, setName] = useState(schedule?.name ?? '')
  const [distance, setDistance] = useState(schedule?.every_distance ? String(Number(schedule.every_distance)) : '')
  const [hours, setHours] = useState(schedule?.every_hours ? String(Number(schedule.every_hours)) : '')
  const [months, setMonths] = useState(schedule?.every_months ? String(schedule.every_months) : '')
  const [notes, setNotes] = useState(schedule?.notes ?? '')
  const monthsOk = !months.trim() || (/^\d+$/.test(months.trim()) && Number(months) >= 1 && Number(months) <= 240)
  const ok = name.trim() && isNumber(distance) && isNumber(hours) && monthsOk && (clean(distance) || clean(hours) || months.trim())
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), every_distance: orNull(distance), every_hours: orNull(hours), every_months: months.trim() ? Number(months) : null, notes }
      return schedule
        ? api('PUT', `/api/v1/service-schedules/${schedule.id}`, body, { 'If-Match': `"${schedule.version}"` })
        : api('POST', `/api/v1/assets/${assetId}/service-schedules`, body)
    },
    onSuccess: async () => { await refresh(); onDone() },
  })
  return (
    <Card>
      <Form onSubmit={(e) => { e.preventDefault(); if (ok) save.mutate() }}>
        <h3 className="font-semibold">{schedule ? 'Edit schedule' : 'New maintenance schedule'}</h3>
        <Field label="What" isRequired maxLength={200} value={name} onChange={setName} description="For example: Engine oil and filter" />
        <p className="text-sm text-stone-600 dark:text-stone-400">Every (fill in one or more; whichever comes first):</p>
        <div className="flex gap-2">
          <div className="min-w-0 flex-1"><Field label={unit === 'mi' ? 'Miles' : 'Km'} inputMode="decimal" maxLength={12} value={distance} onChange={setDistance} isInvalid={!isNumber(distance)} /></div>
          <div className="min-w-0 flex-1"><Field label="Hours" inputMode="decimal" maxLength={10} value={hours} onChange={setHours} isInvalid={!isNumber(hours)} /></div>
          <div className="min-w-0 flex-1"><Field label="Months" inputMode="numeric" maxLength={3} value={months} onChange={setMonths} isInvalid={!monthsOk} /></div>
        </div>
        <Field label="Notes" multiline maxLength={4000} value={notes} onChange={setNotes} description="Parts, oil type, the manual's page…" />
        <ErrorText error={save.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!ok || save.isPending}>Save schedule</Button>
          <Button variant="ghost" onPress={onDone}>Cancel</Button>
        </div>
      </Form>
    </Card>
  )
}

function RecordForm({ assetId, unit, service, schedule, onDone }: {
  assetId: string; unit: string; service: Service; schedule: Schedule | null; onDone: () => void
}) {
  const refresh = useRefresh(assetId)
  const [scheduleId, setScheduleId] = useState(schedule?.id ?? '')
  const [title, setTitle] = useState('')
  const [on, setOn] = useState(today())
  const [distance, setDistance] = useState(service.distance ? String(Number(service.distance)) : '')
  const [hours, setHours] = useState(service.hours ? String(Number(service.hours)) : '')
  const [cost, setCost] = useState('')
  const [notes, setNotes] = useState('')
  const cents = cost.trim() ? parseAmount(cost) : null
  const costOk = !cost.trim() || (cents !== null && cents >= 0)
  const ok = (scheduleId || title.trim()) && isNumber(distance) && isNumber(hours) && costOk
  const add = useMutation({
    mutationFn: () => api('POST', `/api/v1/assets/${assetId}/service-records`, {
      schedule_id: scheduleId || null, title: title.trim() || null, done_on: on,
      distance: orNull(distance), hours: orNull(hours), cost_cents: cents, notes,
    }),
    onSuccess: async () => { await refresh(); onDone() },
  })
  return (
    <Card>
      <Form onSubmit={(e) => { e.preventDefault(); if (ok) add.mutate() }}>
        <h3 className="font-semibold">{schedule ? `Done: ${schedule.name}` : 'Service done'}</h3>
        {!schedule && service.schedules.length > 0 && (
          <label className="block text-sm font-medium">
            Schedule
            <select value={scheduleId} onChange={(e) => setScheduleId(e.target.value)}
              className="mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900">
              <option value="">None (something else)</option>
              {service.schedules.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
        )}
        {!scheduleId && <Field label="What was done" isRequired maxLength={200} value={title} onChange={setTitle} />}
        <DateField label="Date" value={on} onChange={setOn} />
        <div className="flex gap-2">
          <div className="min-w-0 flex-1"><Field label={unit === 'mi' ? 'Odometer (miles)' : 'Odometer (km)'} inputMode="decimal" maxLength={12} value={distance} onChange={setDistance} isInvalid={!isNumber(distance)} /></div>
          <div className="min-w-0 flex-1"><Field label="Hours" inputMode="decimal" maxLength={10} value={hours} onChange={setHours} isInvalid={!isNumber(hours)} /></div>
        </div>
        <Field label="Cost" inputMode="decimal" maxLength={16} value={cost} onChange={setCost} isInvalid={!costOk} />
        <Field label="Notes" multiline maxLength={4000} value={notes} onChange={setNotes} />
        <ErrorText error={add.error} />
        <div className="flex gap-2">
          <Button type="submit" isDisabled={!ok || add.isPending}>Save</Button>
          <Button variant="ghost" onPress={onDone}>Cancel</Button>
        </div>
      </Form>
    </Card>
  )
}

function ScheduleCard({ assetId, schedule: x, unit, canEdit, onDone }: {
  assetId: string; schedule: Schedule; unit: string; canEdit: boolean; onDone: () => void
}) {
  const refresh = useRefresh(assetId)
  const [editing, setEditing] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const remove = useMutation({ mutationFn: () => api('DELETE', `/api/v1/service-schedules/${x.id}`), onSettled: refresh })
  if (editing) return <ScheduleForm assetId={assetId} unit={unit} schedule={x} onDone={() => setEditing(false)} />
  const status = STATUS[x.status]
  return (
    <Card className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{x.name}</p>
        <span className={`rounded-full px-2.5 py-0.5 text-sm font-medium ${status.className}`}>{status.label}</span>
      </div>
      <p className="text-sm text-stone-600 dark:text-stone-400">{every(x, unit)}</p>
      <p className="text-sm">
        {x.last_done_on ? `Last done ${day(x.last_done_on)}` : 'Tap Mark done to record the last time it was done.'}
        {nextDue(x, unit) && <> · {nextDue(x, unit)}</>}
      </p>
      {x.notes && <p className="whitespace-pre-wrap text-sm text-stone-600 dark:text-stone-400">{x.notes}</p>}
      {canEdit && (
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="secondary" onPress={onDone}>Mark done</Button>
          <Button variant="ghost" onPress={() => setEditing(true)}>Edit</Button>
          <Button variant="danger-ghost" onPress={() => (confirm ? remove.mutate() : setConfirm(true))} isDisabled={remove.isPending}>
            {confirm ? 'Tap again to delete' : 'Delete'}
          </Button>
        </div>
      )}
      <ErrorText error={remove.error} />
    </Card>
  )
}

function History({ assetId, service: s }: { assetId: string; service: Service }) {
  const refresh = useRefresh(assetId)
  const removeRecord = useMutation({ mutationFn: (id: string) => api('DELETE', `/api/v1/service-records/${id}`), onSettled: refresh })
  const removeReading = useMutation({ mutationFn: (id: string) => api('DELETE', `/api/v1/asset-readings/${id}`), onSettled: refresh })
  const unit = s.distance_unit
  const meters = (r: { distance: string | null; hours: string | null }) =>
    [r.distance && `${num(r.distance)} ${unit}`, r.hours && `${num(r.hours)} h`].filter(Boolean).join(' · ')
  return (
    <>
      {s.records.length > 0 && (
        <details className="rounded-2xl">
          <summary className="min-h-11 cursor-pointer py-2 font-medium">Service history ({s.records.length})</summary>
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {s.records.map((r) => (
              <li key={r.id} className="flex items-start gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{r.title}</p>
                  <p className="text-sm text-stone-500">{[day(r.done_on), meters(r), r.cost_cents !== null && formatCents(r.cost_cents)].filter(Boolean).join(' · ')}</p>
                  {r.notes && <p className="whitespace-pre-wrap text-sm text-stone-600 dark:text-stone-400">{r.notes}</p>}
                </div>
                {s.can_edit && <Button variant="ghost" aria-label={`Delete ${r.title} on ${day(r.done_on)}`} onPress={() => removeRecord.mutate(r.id)}>✕</Button>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {s.readings.length > 0 && (
        <details className="rounded-2xl">
          <summary className="min-h-11 cursor-pointer py-2 font-medium">Readings ({s.readings.length})</summary>
          <ul className="divide-y divide-stone-200 rounded-2xl bg-white ring-1 ring-stone-200 dark:divide-stone-800 dark:bg-stone-900 dark:ring-stone-800">
            {s.readings.map((r) => (
              <li key={r.id} className="flex items-center gap-2 px-3">
                <span className="min-h-11 flex-1 py-2.5">{day(r.read_on)} · {meters(r)}</span>
                {s.can_edit && <Button variant="ghost" aria-label={`Delete reading of ${day(r.read_on)}`} onPress={() => removeReading.mutate(r.id)}>✕</Button>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <ErrorText error={removeRecord.error ?? removeReading.error} />
    </>
  )
}

function DateField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input type="date" required value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900" />
    </label>
  )
}
