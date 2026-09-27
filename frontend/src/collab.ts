// Real-time co-editing connection for one note (ADR 0011). Speaks the standard Yjs sync and
// awareness protocol over a same-origin WebSocket; the session cookie authenticates it and the
// server checks Origin and permissions (SECURITY.md §7.15).
import * as decoding from 'lib0/decoding'
import * as encoding from 'lib0/encoding'
import * as awarenessProtocol from 'y-protocols/awareness'
import * as syncProtocol from 'y-protocols/sync'
import type * as Y from 'yjs'

const SYNC = 0
const AWARENESS = 1

export type Status = 'connecting' | 'connected' | 'offline' | 'denied'

// Close codes after which retrying can't help: signed out, no access, or the note is gone.
const FINAL = new Set([4401, 4403, 4404])

export class NoteConnection {
  readonly awareness: awarenessProtocol.Awareness
  status: Status = 'connecting'
  synced = false
  private socket: WebSocket | null = null
  private retries = 0
  private timer: ReturnType<typeof setTimeout> | undefined
  private destroyed = false
  private readonly noteId: string
  private readonly doc: Y.Doc
  private readonly readOnly: boolean
  private readonly onChange: (c: NoteConnection) => void

  constructor(noteId: string, doc: Y.Doc, readOnly: boolean, onChange: (c: NoteConnection) => void) {
    this.noteId = noteId
    this.doc = doc
    this.readOnly = readOnly
    this.onChange = onChange
    this.awareness = new awarenessProtocol.Awareness(doc)
    doc.on('update', this.onDocUpdate)
    this.awareness.on('update', this.onAwarenessUpdate)
    window.addEventListener('online', this.reconnectNow)
    this.connect()
  }

  private url(): string {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${scheme}://${window.location.host}/api/v1/collab/notes/${this.noteId}`
  }

  private setStatus(status: Status): void {
    this.status = status
    this.onChange(this)
  }

  private connect(): void {
    if (this.destroyed) return
    const socket = new WebSocket(this.url())
    socket.binaryType = 'arraybuffer'
    this.socket = socket
    this.setStatus('connecting')
    socket.onopen = () => {
      this.retries = 0
      this.setStatus('connected')
      const encoder = encoding.createEncoder()
      encoding.writeVarUint(encoder, SYNC)
      syncProtocol.writeSyncStep1(encoder, this.doc)
      this.send(encoding.toUint8Array(encoder))
      if (this.awareness.getLocalState() !== null) {
        this.sendAwareness([this.doc.clientID])
      }
    }
    socket.onmessage = (event: MessageEvent<ArrayBuffer>) => this.receive(new Uint8Array(event.data))
    socket.onclose = (event) => {
      this.socket = null
      this.synced = false
      // Others' cursors are stale once we're disconnected.
      awarenessProtocol.removeAwarenessStates(
        this.awareness,
        [...this.awareness.getStates().keys()].filter((id) => id !== this.doc.clientID),
        this,
      )
      if (this.destroyed) return
      if (FINAL.has(event.code)) {
        this.setStatus('denied')
        return
      }
      this.setStatus('offline')
      const delay = Math.min(30_000, 1000 * 2 ** this.retries) * (0.5 + Math.random() / 2)
      this.retries += 1
      this.timer = setTimeout(() => this.connect(), delay)
    }
  }

  private reconnectNow = (): void => {
    if (this.socket || this.destroyed || this.status === 'denied') return
    clearTimeout(this.timer)
    this.connect()
  }

  private receive(data: Uint8Array): void {
    const decoder = decoding.createDecoder(data)
    const type = decoding.readVarUint(decoder)
    if (type === SYNC) {
      const encoder = encoding.createEncoder()
      encoding.writeVarUint(encoder, SYNC)
      const kind = syncProtocol.readSyncMessage(decoder, encoder, this.doc, this)
      // A viewer never sends document content, not even its reply to the server's state.
      if (encoding.length(encoder) > 1 && !this.readOnly) this.send(encoding.toUint8Array(encoder))
      if (kind === syncProtocol.messageYjsSyncStep2 && !this.synced) {
        this.synced = true
        this.onChange(this)
      }
    } else if (type === AWARENESS) {
      awarenessProtocol.applyAwarenessUpdate(this.awareness, decoding.readVarUint8Array(decoder), this)
    }
  }

  private send(message: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(message as Uint8Array<ArrayBuffer>)
  }

  private sendAwareness(clients: number[]): void {
    const encoder = encoding.createEncoder()
    encoding.writeVarUint(encoder, AWARENESS)
    encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(this.awareness, clients))
    this.send(encoding.toUint8Array(encoder))
  }

  private onDocUpdate = (update: Uint8Array, origin: unknown): void => {
    if (origin === this || this.readOnly) return
    const encoder = encoding.createEncoder()
    encoding.writeVarUint(encoder, SYNC)
    syncProtocol.writeUpdate(encoder, update)
    this.send(encoding.toUint8Array(encoder))
  }

  private onAwarenessUpdate = (
    { added, updated, removed }: { added: number[]; updated: number[]; removed: number[] },
    origin: unknown,
  ): void => {
    if (origin === this) return
    this.sendAwareness([...added, ...updated, ...removed])
  }

  destroy(): void {
    this.destroyed = true
    clearTimeout(this.timer)
    window.removeEventListener('online', this.reconnectNow)
    awarenessProtocol.removeAwarenessStates(this.awareness, [this.doc.clientID], 'local')
    this.doc.off('update', this.onDocUpdate)
    this.awareness.off('update', this.onAwarenessUpdate)
    this.awareness.destroy()
    this.socket?.close()
  }
}
