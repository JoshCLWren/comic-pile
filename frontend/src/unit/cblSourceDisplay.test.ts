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
})
