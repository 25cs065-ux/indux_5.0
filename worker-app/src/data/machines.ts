// Copy of docs/lists/machines.json (kept inside worker-app so the build does
// not depend on other folders). Update both if the machine list changes.

export interface Machine {
  machine_id: string
  name: string
  model: string
  location: string
}

export const MACHINES: readonly Machine[] = [
  { machine_id: 'compressor-01', name: 'Compressor #01', model: 'Atlas Copco GA 22', location: 'Plant Room A' },
  { machine_id: 'compressor-02', name: 'Compressor #02', model: 'Atlas Copco GA 22', location: 'Plant Room A' },
]

/** The listed machine whose ID matches exactly, or null. IDs are never normalized. */
export function findMachine(machineId: string): Machine | null {
  return MACHINES.find((m) => m.machine_id === machineId) ?? null
}
