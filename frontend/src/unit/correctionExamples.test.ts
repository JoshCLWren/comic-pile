import { describe, expect, it } from 'vitest'

import { selectCorrectionExamples } from '../utils/correctionExamples'

describe('selectCorrectionExamples', () => {
  it('returns no examples when history is empty', () => {
    expect(selectCorrectionExamples({ rated: [], history: [] })).toEqual({})
  })

  it('illustrates familiar with top-rated comics, never invented titles', () => {
    const result = selectCorrectionExamples({
      rated: [
        { title: 'Planetary', rating: 4.5, format: 'trade' },
        { title: 'Hellboy', rating: 4.0, format: 'trade' },
        { title: 'Crossover X', rating: 2.0, format: 'omnibus' },
      ],
      history: [],
    })

    expect(result.something_familiar).toBe('Planetary / Hellboy')
    // Low-rated comics never illustrate the liked-history option.
    expect(result.something_familiar).not.toContain('Crossover X')
  })

  it('requires genuine positive signal before illustrating familiar', () => {
    const result = selectCorrectionExamples({
      rated: [{ title: 'Meh Comic', rating: 3.0, format: 'issue' }],
      history: [],
    })

    expect(result.something_familiar).toBeUndefined()
  })

  it('never illustrates an option with the comic being rejected', () => {
    const result = selectCorrectionExamples({
      rated: [
        { title: 'Planetary', rating: 5.0, format: 'trade' },
        { title: 'Hellboy', rating: 4.5, format: 'trade' },
      ],
      history: [{ title: 'Planetary', format: 'trade' }],
      activeTitle: 'planetary',
      activeFormat: 'trade',
    })

    for (const title of Object.values(result)) {
      expect(title.toLowerCase()).not.toContain('planetary')
    }
    expect(result.something_familiar).toBe('Hellboy')
  })

  it('illustrates change of pace with a liked comic from a different format lane', () => {
    const result = selectCorrectionExamples({
      rated: [
        { title: 'Planetary', rating: 5.0, format: 'trade' },
        { title: 'Hellboy', rating: 4.8, format: 'trade' },
        { title: 'Saga', rating: 4.5, format: 'issue' },
      ],
      history: [],
    })

    expect(result.something_familiar).toBe('Planetary / Hellboy')
    expect(result.something_different).toBe('Saga')
  })

  it('omits change of pace when liked history is single-format', () => {
    const result = selectCorrectionExamples({
      rated: [
        { title: 'Planetary', rating: 5.0, format: 'trade' },
        { title: 'Hellboy', rating: 4.5, format: 'trade' },
      ],
      history: [],
    })

    expect(result.something_different).toBeUndefined()
  })

  it('illustrates lighter with a single-issue read from user history', () => {
    const result = selectCorrectionExamples({
      rated: [],
      history: [
        { title: 'Big Omnibus', format: 'omnibus' },
        { title: 'Superman’s Pal Jimmy Olsen #134', format: 'issue' },
      ],
    })

    expect(result.even_easier).toBe('Superman’s Pal Jimmy Olsen #134')
  })

  it('omits lighter when no light-commitment read exists in history', () => {
    const result = selectCorrectionExamples({
      rated: [],
      history: [{ title: 'Big Omnibus', format: 'omnibus' }],
    })

    expect(result.even_easier).toBeUndefined()
  })

  it('illustrates same effort with a same-format peer of the current roll', () => {
    const result = selectCorrectionExamples({
      rated: [],
      history: [
        { title: 'Current Pick', format: 'trade' },
        { title: 'Another Trade', format: 'trade' },
        { title: 'Single Issue', format: 'issue' },
      ],
      activeTitle: 'Current Pick',
      activeFormat: 'trade',
    })

    expect(result.keep_level_different).toBe('Another Trade')
  })

  it('omits same effort when the active format is unknown', () => {
    const result = selectCorrectionExamples({
      rated: [],
      history: [{ title: 'Another Trade', format: 'trade' }],
      activeTitle: 'Current Pick',
      activeFormat: null,
    })

    expect(result.keep_level_different).toBeUndefined()
  })

  it('never returns a surprise-me example', () => {
    const result = selectCorrectionExamples({
      rated: [{ title: 'Planetary', rating: 5.0, format: 'trade' }],
      history: [{ title: 'Saga', format: 'issue' }],
    })

    expect(result.pure_random).toBeUndefined()
  })
})
