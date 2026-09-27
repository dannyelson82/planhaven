// Shared building blocks: React Aria components with Planhaven styling (ADR 0014).
// Touch targets are at least 44px; everything works with keyboard and screen readers.
import type { ReactNode } from 'react'
import {
  Button as AriaButton,
  type ButtonProps,
  FieldError,
  Form as AriaForm,
  type FormProps,
  Input,
  Label,
  Link as AriaLink,
  TextArea,
  TextField,
} from 'react-aria-components'
import { navigate } from './router.ts'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 pressed:bg-brand-700',
  secondary:
    'bg-white text-stone-900 ring-1 ring-stone-300 hover:bg-stone-100 dark:bg-stone-900 dark:text-stone-100 dark:ring-stone-700 dark:hover:bg-stone-800',
  danger: 'bg-red-600 text-white hover:bg-red-700',
  ghost: 'text-stone-700 hover:bg-stone-200 dark:text-stone-300 dark:hover:bg-stone-800',
}

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonProps & { variant?: Variant; className?: string }) {
  return (
    <AriaButton
      {...props}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 font-medium transition disabled:opacity-50 ${variants[variant]} ${className}`}
    />
  )
}

export function Field({
  label,
  type = 'text',
  multiline = false,
  description,
  ...props
}: {
  label: string
  name?: string
  type?: string
  multiline?: boolean
  description?: string
  value?: string
  onChange?: (v: string) => void
  isRequired?: boolean
  autoComplete?: string
  inputMode?: 'numeric' | 'text' | 'email'
  autoFocus?: boolean
  maxLength?: number
  minLength?: number
}) {
  const input =
    'mt-1 block w-full rounded-xl border border-stone-300 bg-white px-3 py-2.5 dark:border-stone-700 dark:bg-stone-900 invalid:border-red-500'
  return (
    <TextField {...props} type={type} className="block">
      <Label className="text-sm font-medium">{label}</Label>
      {multiline ? <TextArea className={`${input} min-h-24`} /> : <Input className={input} />}
      {description && <p className="mt-1 text-sm text-stone-500">{description}</p>}
      <FieldError className="mt-1 text-sm text-red-600" />
    </TextField>
  )
}

export function Form(props: FormProps) {
  return <AriaForm {...props} className="space-y-4" />
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
      {message}
    </p>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl bg-white p-4 shadow-sm ring-1 ring-stone-200 dark:bg-stone-900 dark:ring-stone-800 ${className}`}>
      {children}
    </div>
  )
}

export function Link({ to, children, className = '' }: { to: string; children: ReactNode; className?: string }) {
  return (
    <AriaLink
      href={to}
      onPress={() => navigate(to)}
      className={`underline-offset-2 hover:underline ${className}`}
    >
      {children}
    </AriaLink>
  )
}

/** Centered single-column page for sign-in flows. */
export function AuthPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4 pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)]">
      <p className="mb-2 text-center text-sm font-semibold uppercase tracking-wider text-brand-600">Planhaven</p>
      <h1 className="mb-6 text-center text-2xl font-bold">{title}</h1>
      <Card>{children}</Card>
    </main>
  )
}
