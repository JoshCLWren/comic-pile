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
 * Remove leading metadata tags such as `[Marvel] [2024-2026]` from a title.
 *
 * CBL list names often carry publisher and coverage tags before the
 * reading-order title. The default view shows the title, not the tags.
 *
 * @param value - A list title or filename.
 * @returns The title without its leading bracketed metadata tags.
 */
function stripMetadataTags(value: string): string {
  return value.replace(/^(\[[^\]]+\]\s*)+/, '').trim()
}

/**
 * Extract a reader-friendly source name from the full source path.
 *
 * The source path may include directories and the .cbl extension.
 * This function strips those to show just the name.
 *
 * @param sourcePath - The full CBL source path.
 * @returns A reader-friendly name without the .cbl extension.
 *
 * @example
 * displayCblSourceName('Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl')
 * // returns 'The New Marvel Ultimate Universe 2.0 (CBH)'
 */
export function displayCblSourceName(sourcePath: string): string | null {
  const normalized = normalizedPath(sourcePath)
  if (!normalized) return null

  // Remove the .cbl extension if present
  let name = normalized.replace(/\.cbl$/, '')

  // If the path starts with a directory and the name is just the filename
  // (after stripping .cbl), extract just the filename
  const lastSlashIndex = name.lastIndexOf('/')
  if (lastSlashIndex >= 0) {
    name = name.slice(lastSlashIndex + 1)
  }

  if (!name || name === MIRROR_NAME) return null

  name = stripMetadataTags(name)

  if (!name) return null

  return name
}

/**
 * Return the reader-friendly title for a CBL source list.
 *
 * The supplied list title wins whenever it is readable, because it carries the
 * reading-order name the CBL file declares rather than a filename. Leading
 * metadata tags (`[Marvel] [2024-2026]`) and a trailing `.cbl` extension are
 * removed so the default view never shows file-path noise. The stored source
 * path is only a fallback for sources that declare no readable title.
 *
 * @param name - The supplied list title, when the source declares one.
 * @param sourcePath - The stored CBL source path.
 * @returns A reader-friendly title, or null when nothing readable remains.
 *
 * @example
 * displayCblSourceTitle(
 *   '[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)',
 *   'Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl',
 * )
 * // returns 'The New Marvel Ultimate Universe 2.0 (CBH)'
 */
export function displayCblSourceTitle(
  name: string | null | undefined,
  sourcePath: string,
): string | null {
  const supplied = name?.trim()
  if (supplied) {
    const title = stripMetadataTags(supplied.replace(/\.cbl$/i, '').trim())
    if (title) return title
  }
  return displayCblSourceName(sourcePath)
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
    if (!fileName.includes('.')) return null
    return fileName.replace(/\.cbl$/, '') || null
  }
  return normalized
}
