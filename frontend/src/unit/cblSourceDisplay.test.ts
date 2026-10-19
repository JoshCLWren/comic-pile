import { describe, expect, it } from 'vitest'
import {
  displayCblRepository,
  displayCblSourceName,
  displayCblSourcePath,
  isFilesystemSourceLocation,
} from '../utils/cblSourceDisplay'

describe('cblSourceDisplay', () => {
  it('extracts a reader-friendly name without .cbl extension', () => {
    expect(displayCblSourceName('Marvel/Events/CBH/[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH).cbl')).toBe(
      'The New Marvel Ultimate Universe 2.0 (CBH)',
    )
    expect(displayCblSourceName('Ultimate.cbl')).toBe('Ultimate')
    expect(displayCblSourceName('/tmp/lists/Ultimate.cbl')).toBe('Ultimate')
    expect(displayCblSourceName('Marvel/Events/CBH/Ultimate.cbl')).toBe('Ultimate')
  })

  it('returns null for empty strings', () => {
    expect(displayCblSourceName('')).toBeNull()
    expect(displayCblSourceName('   ')).toBeNull()
  })

  it('returns null when no name remains after stripping', () => {
    expect(displayCblSourceName('/')).toBeNull()
    expect(displayCblSourceName('dir/')).toBeNull()
    expect(displayCblSourceName('/mnt/bigdata/CBL-ReadingLists')).toBeNull()
  })

  it('does not strip .cbl when not at the end', () => {
    expect(displayCblSourceName('file.cbl.backup')).toBe('file.cbl.backup')
  })

  it('works with Windows-style paths', () => {
    expect(displayCblSourceName('C:\\path\\to\\file.cbl')).toBe('file')
    expect(displayCblSourceName('C:\\path\\to\\Marvel\\Ultimate.cbl')).toBe('Ultimate')
  })

  it('maps the production mirror path to the public repository', () => {
    expect(isFilesystemSourceLocation('/mnt/bigdata/CBL-ReadingLists')).toBe(true)
    expect(displayCblRepository('/mnt/bigdata/CBL-ReadingLists')).toBe(
      'JoshCLWren/CBL-ReadingLists',
    )
    expect(displayCblSourcePath('/mnt/bigdata/CBL-ReadingLists/Marvel/Ultimate.cbl')).toBe(
      'Marvel/Ultimate.cbl',
    )
  })

  it('keeps GitHub-style repositories and relative source paths', () => {
    expect(displayCblRepository('JoshCLWren/CBL-ReadingLists')).toBe(
      'JoshCLWren/CBL-ReadingLists',
    )
    expect(displayCblSourcePath('Marvel/Ultimate.cbl')).toBe('Marvel/Ultimate.cbl')
    expect(isFilesystemSourceLocation('Marvel/Ultimate.cbl')).toBe(false)
  })

  it('does not return a bare host directory as a source path', () => {
    expect(displayCblSourcePath('/mnt/bigdata/CBL-ReadingLists')).toBeNull()
  })

  it('recognizes file URLs, relative mnt paths, and nested /mnt/ locations', () => {
    expect(isFilesystemSourceLocation('file:/mnt/bigdata/CBL-ReadingLists')).toBe(true)
    expect(isFilesystemSourceLocation('mnt/bigdata/CBL-ReadingLists')).toBe(true)
    expect(isFilesystemSourceLocation('mirror/mnt/CBL-ReadingLists')).toBe(true)
    expect(displayCblRepository('')).toBeNull()
    expect(displayCblRepository('/var/lib/comicpile')).toBeNull()
    expect(displayCblRepository('/data/CBL-ReadingLists/')).toBe('JoshCLWren/CBL-ReadingLists')
  })

  it('falls back to a filename for other filesystem paths and ignores blanks', () => {
    expect(displayCblSourcePath('')).toBeNull()
    expect(displayCblSourcePath('/tmp/lists/Ultimate.cbl')).toBe('Ultimate')
    expect(displayCblSourcePath('/tmp/lists')).toBeNull()
    expect(displayCblSourcePath('/mnt/bigdata/CBL-ReadingLists/')).toBeNull()
  })
})

