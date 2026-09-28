import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, uploadFile } from '../api.ts'
import { Button, Card, ErrorText } from '../ui.tsx'

type Attachment = {
  id: string
  filename: string
  kind: string
  size: number
  has_thumbnail: boolean
  metadata_kept: boolean
  created_at: string
}

function sizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Photos and files on a project page (those given their own tile are left out). On a phone,
 * "Take photo" opens the camera. */
export function ProjectAttachments({ projectId, canEdit, exclude = [] }: { projectId: string; canEdit: boolean; exclude?: string[] }) {
  const client = useQueryClient()
  const key = ['attachments', projectId]
  const files = useQuery({ queryKey: key, queryFn: () => api<Attachment[]>('GET', `/api/v1/projects/${projectId}/attachments`) })
  const [progress, setProgress] = useState<string | null>(null)
  const [keepLocation, setKeepLocation] = useState(false)
  const pick = useRef<HTMLInputElement>(null)
  const camera = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: async (list: File[]) => {
      for (const [i, file] of list.entries()) {
        setProgress(list.length > 1 ? `Uploading ${i + 1} of ${list.length}…` : 'Uploading…')
        const params = new URLSearchParams({ filename: file.name || 'photo.jpg', ...(keepLocation ? { keep_metadata: 'true' } : {}) })
        await uploadFile(`/api/v1/projects/${projectId}/attachments?${params}`, file)
      }
    },
    onSettled: async () => { setProgress(null); await client.invalidateQueries({ queryKey: key }) },
  })
  const remove = useMutation({
    mutationFn: (a: Attachment) => api('DELETE', `/api/v1/attachments/${a.id}`),
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  })
  const onFiles = (input: HTMLInputElement) => {
    const list = [...(input.files ?? [])]
    input.value = ''
    if (list.length) upload.mutate(list)
  }
  const listed = (files.data ?? []).filter((a) => !exclude.includes(a.id))
  const photos = listed.filter((a) => a.has_thumbnail)
  const others = listed.filter((a) => !a.has_thumbnail)
  return (
    <section aria-label="Photos and files" className="space-y-3">
      <h2 className="text-lg font-semibold">Photos and files</h2>
      {photos.length > 0 && (
        <ul className="grid grid-cols-3 gap-2 @xl:grid-cols-4 @3xl:grid-cols-6">
          {photos.map((a) => (
            <li key={a.id} className="relative">
              <a href={a.metadata_kept ? `/api/v1/attachments/${a.id}/download` : `/api/v1/attachments/${a.id}/view`} target="_blank" rel="noopener noreferrer">
                <img src={`/api/v1/attachments/${a.id}/thumbnail`} alt={a.filename} loading="lazy"
                  className="aspect-square w-full rounded-xl bg-stone-200 object-cover dark:bg-stone-800" />
              </a>
              {canEdit && (
                <Button variant="secondary" aria-label={`Delete ${a.filename}`} onPress={() => remove.mutate(a)}
                  className="absolute right-1 top-1 min-h-8 min-w-8 rounded-full px-0 text-sm opacity-90">✕</Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {others.length > 0 && (
        <ul className="space-y-2">
          {others.map((a) => (
            <li key={a.id}>
              <Card className="flex items-center gap-2 py-2">
                <a href={`/api/v1/attachments/${a.id}/download`} download className="min-w-0 flex-1 truncate font-medium text-brand-700 underline-offset-2 hover:underline dark:text-brand-100">
                  {a.filename}
                </a>
                <span className="text-sm text-stone-500">{sizeText(a.size)}</span>
                {canEdit && <Button variant="ghost" aria-label={`Delete ${a.filename}`} onPress={() => remove.mutate(a)}>✕</Button>}
              </Card>
            </li>
          ))}
        </ul>
      )}
      {files.data?.length === 0 && <p className="text-sm text-stone-500">No photos or files yet.</p>}
      {canEdit && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onPress={() => camera.current?.click()} isDisabled={upload.isPending} className="md:hidden">Take photo</Button>
            <Button variant="secondary" onPress={() => pick.current?.click()} isDisabled={upload.isPending}>Add photos or files</Button>
          </div>
          <input ref={camera} type="file" accept="image/*" capture="environment" hidden aria-hidden="true" tabIndex={-1} onChange={(e) => onFiles(e.currentTarget)} />
          <input ref={pick} type="file" multiple hidden aria-label="Choose files" onChange={(e) => onFiles(e.currentTarget)} data-testid="file-input" />
          <label className="flex min-h-11 items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
            <input type="checkbox" checked={keepLocation} onChange={(e) => setKeepLocation(e.target.checked)} className="size-4 accent-brand-600" />
            Keep photo location and camera details (removed by default)
          </label>
          {progress && <p role="status" className="text-sm text-stone-500">{progress}</p>}
        </div>
      )}
      <ErrorText error={upload.error ?? remove.error ?? files.error} />
    </section>
  )
}

/** One photo or file in its own tile on the project page: a photo shown large. */
export function FileTile({ projectId, fileId }: { projectId: string; fileId: string }) {
  const files = useQuery({ queryKey: ['attachments', projectId], queryFn: () => api<Attachment[]>('GET', `/api/v1/projects/${projectId}/attachments`) })
  const a = files.data?.find((f) => f.id === fileId)
  if (!a) return null // deleted since, or not shared with this person
  const href = a.metadata_kept || !a.has_thumbnail ? `/api/v1/attachments/${a.id}/download` : `/api/v1/attachments/${a.id}/view`
  return (
    <section aria-label={`File: ${a.filename}`}>
      <Card className="space-y-2">
        {a.has_thumbnail && (
          <a href={href} target="_blank" rel="noopener noreferrer">
            <img src={`/api/v1/attachments/${a.id}/${a.metadata_kept ? 'thumbnail' : 'view'}`} alt={a.filename} loading="lazy"
              className="max-h-96 w-full rounded-xl bg-stone-200 object-contain dark:bg-stone-800" />
          </a>
        )}
        <p className="flex items-center gap-2">
          <a href={href} {...(a.has_thumbnail ? { target: '_blank', rel: 'noopener noreferrer' } : { download: true })}
            className="min-w-0 flex-1 truncate font-medium text-brand-700 underline-offset-2 hover:underline dark:text-brand-100">{a.filename}</a>
          <span className="text-sm text-stone-500">{sizeText(a.size)}</span>
        </p>
      </Card>
    </section>
  )
}
