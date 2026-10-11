// Machine IDs are kept exactly as given (no trimming, casing or
// separator changes) until the backend team confirms the canonical format.

const STORAGE_KEY = 'indux.lastMachineId'

/** Reads `?machine=` from a QR link. Returns null if absent or blank. */
export function machineFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get('machine')
  return value !== null && value.trim() !== '' ? value : null
}

export function loadLastMachine(): string | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value && value.trim() !== '' ? value : null
  } catch {
    return null
  }
}

export function saveLastMachine(machineId: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, machineId)
  } catch {
    // Storage may be unavailable (private mode); remembering is optional.
  }
}

/** QR link first, then the last machine used on this device, else none. */
export function initialMachineId(search: string): string {
  return machineFromSearch(search) ?? loadLastMachine() ?? ''
}

export function hasOuterWhitespace(machineId: string): boolean {
  return machineId !== machineId.trim()
}
