// Passkeys through the browser's native WebAuthn JSON helpers (no extra library).

export function passkeysSupported(): boolean {
  return (
    typeof PublicKeyCredential !== 'undefined' &&
    'parseCreationOptionsFromJSON' in PublicKeyCredential &&
    'parseRequestOptionsFromJSON' in PublicKeyCredential
  )
}

function toJSON(credential: Credential | null): unknown {
  if (!(credential instanceof PublicKeyCredential)) throw new Error('No passkey was selected.')
  return credential.toJSON()
}

export async function createPasskey(options: Record<string, unknown>): Promise<unknown> {
  const publicKey = PublicKeyCredential.parseCreationOptionsFromJSON(
    options as unknown as PublicKeyCredentialCreationOptionsJSON,
  )
  return toJSON(await navigator.credentials.create({ publicKey }))
}

export async function getPasskey(options: Record<string, unknown>): Promise<unknown> {
  const publicKey = PublicKeyCredential.parseRequestOptionsFromJSON(
    options as unknown as PublicKeyCredentialRequestOptionsJSON,
  )
  return toJSON(await navigator.credentials.get({ publicKey }))
}
