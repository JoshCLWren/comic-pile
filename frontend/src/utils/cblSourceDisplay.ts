/**
 * Strip local-mirror filesystem paths from CBL source identity shown to readers.
 *
 * Production historically stored `/mnt/bigdata/CBL-ReadingLists` as the source
 * repository. That path must not appear on `/cbl-sources` or plan pages.
 */

const MIRROR_NAME = 'CBL-ReadingLists'
const PUBLIC_REPOSITORY = 'JoshCLWren/CBL-ReadingLists'

function normalizedPath(value: string): string {
  return value.trim().replace(/\\/g, '/')
}

/**
 * Return whether a stored source location looks like a local filesystem path.
 *
 * @param value - Repository or source path from the CBL API.
 * @returns True when `value` is an absolute or `/mnt/` path.
 */
export function isFilesystemSourceLocation(value: string): boolean {
  const normalized = normalizedPath(value)
  return (
    normalized.startsWith('/') ||
    normalized.startsWith('file:') ||
    normalized.startsWith('mnt/') ||
    normalized.includes('/mnt/')
  )
}

/**
 * Return a reader-safe repository name, or null when nothing public remains.
 *
 * @param repository - Stored repository or local mirror path.
 * @returns A GitHub-style repository, the original non-path value, or null.
 */
export function displayCblRepository(repository: string): string | null {
  const trimmed = repository.trim()
  if (!trimmed) return null
  if (!isFilesystemSourceLocation(trimmed)) return trimmed
  const normalized = normalizedPath(trimmed)
  if (normalized.endsWith(MIRROR_NAME) || normalized.includes(`/${MIRROR_NAME}`)) {
    return PUBLIC_REPOSITORY
  }
  return null
}

/**
 * Return a reader-safe source path without server directory prefixes.
 *
 * @param sourcePath - Stored CBL source path.
 * @returns A relative path or filename, or null when the path would leak a host directory.
 */
export function displayCblSourcePath(sourcePath: string): string | null {
  const normalized = normalizedPath(sourcePath)
  if (!normalized) return null
  const marker = `${MIRROR_NAME}/`
  const markerIndex = normalized.indexOf(marker)
  if (markerIndex >= 0) {
    return normalized.slice(markerIndex + marker.length) || null
  }
  if (isFilesystemSourceLocation(normalized)) {
    const fileName = normalized.split('/').pop() ?? ''
    return fileName.includes('.') ? fileName : null
  }
  return normalized
}
