export function readValue(value: string): string {
  return `real:${value}`
}

export const service = {
  read(value: number): string {
    return `real:${value}`
  },
}

export const untouched = 'untouched'
