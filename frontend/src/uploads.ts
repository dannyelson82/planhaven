// Uploading a document (an estimate, a receipt) to a project's files.
import { uploadFile } from './api.ts'

export type UploadedFile = { id: string; filename: string }

export const DOCUMENT_TYPES = 'application/pdf,image/*,.heic,.heif'

export function uploadToProject(projectId: string, file: File): Promise<UploadedFile> {
  const params = new URLSearchParams({ filename: file.name || 'document' })
  return uploadFile<UploadedFile>(`/api/v1/projects/${projectId}/attachments?${params}`, file)
}
