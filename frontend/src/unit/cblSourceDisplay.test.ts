import { describe, expect, it } from 'vitest'
import {
  displayCblRepository,
  displayCblSourcePath,
  isFilesystemSourceLocation,
} from '../utils/cblSourceDisplay'

describe('cblSourceDisplay', () => {
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
    expect(displayCblSourcePath('/tmp/lists/Ultimate.cbl')).toBe('Ultimate.cbl')
    expect(displayCblSourcePath('/tmp/lists')).toBeNull()
    expect(displayCblSourcePath('/mnt/bigdata/CBL-ReadingLists/')).toBeNull()
  })
})

