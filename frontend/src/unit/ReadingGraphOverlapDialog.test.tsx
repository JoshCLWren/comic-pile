import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ReadingGraphOverlapDialog from '../components/ReadingGraphOverlapDialog'
import type { ReadingGraphChoices } from '../utils/readingGraphOverlaps'
import {
  MISTER_MIRACLE_OVERLAP,
  SECOND_MISTER_MIRACLE_OVERLAP,
  readingGraphPreview,
  withoutOverlap,
} from './readingGraphFixture'

interface RenderArgs {
  choices?: ReadingGraphChoices
  overlaps?: typeof MISTER_MIRACLE_OVERLAP[]
}

function renderDialog({ choices = {}, overlaps }: RenderArgs = {}) {
  const preview = readingGraphPreview(
    overlaps ? { overlaps } : undefined,
  )
  const onChoose = vi.fn()
  const onClose = vi.fn()
  const onDone = vi.fn()
  const view = render(
    <ReadingGraphOverlapDialog
      isOpen
      preview={preview}
      choices={choices}
      onChoose={onChoose}
      onClose={onClose}
      onDone={onDone}
    />,
  )
  const rerender = (nextChoices: ReadingGraphChoices, nextOverlaps = overlaps) => {
    view.rerender(
      <ReadingGraphOverlapDialog
        isOpen
        preview={readingGraphPreview(nextOverlaps ? { overlaps: nextOverlaps } : undefined)}
        choices={nextChoices}
        onChoose={onChoose}
        onClose={onClose}
        onDone={onDone}
      />,
    )
  }
  return { onChoose, onClose, onDone, rerender, preview }
}

describe('ReadingGraphOverlapDialog', () => {
  it('asks about one series pair and shows what waits and what keeps rolling', async () => {
    const user = userEvent.setup()
    renderDialog()

    expect(
      screen.getByRole('heading', { name: 'Resolve overlapping series' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Overlap 1 of 1')
    expect(
      screen.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (1989) waits?',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Waiting right now: Justice League International #2/)).toBeInTheDocument()

    const continuing = screen.getByRole('radio', {
      name: /Mister Miracle waits; JLI continues/,
    })
    expect(continuing).toHaveAttribute('aria-checked', 'false')
    expect(
      screen.getByText('Keeps rolling: Justice League International #2'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Still waits: Mister Miracle #1, Mister Miracle #2, Justice League International #3'),
    ).toBeInTheDocument()

    const protect = screen.getByRole('radio', { name: /Keep the full chosen order/ })
    expect(
      screen.getByText('Still waits: Justice League International #2, Justice League International #3'),
    ).toBeInTheDocument()
    expect(protect).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Use these choices' })).toBeDisabled()

    await user.click(continuing)
    expect(screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ })).toBeInTheDocument()
  })

  it('records the exact volume pair the reader answered', async () => {
    const user = userEvent.setup()
    const { onChoose } = renderDialog()

    await user.click(
      screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    )
    expect(onChoose).toHaveBeenCalledWith(
      MISTER_MIRACLE_OVERLAP.overlap_id,
      'continue_series',
    )
  })

  it('enables finishing only after every series is decided', async () => {
    const user = userEvent.setup()
    const { onDone, rerender } = renderDialog({
      overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
    })

    expect(screen.getByRole('status')).toHaveTextContent('Overlap 1 of 2')
    await user.click(
      screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    )
    // The page applies the answer; the dialog only advances once it is present.
    rerender({ [MISTER_MIRACLE_OVERLAP.overlap_id]: 'continue_series' }, [
      MISTER_MIRACLE_OVERLAP,
      SECOND_MISTER_MIRACLE_OVERLAP,
    ])
    await user.click(screen.getByRole('button', { name: 'Next series' }))

    expect(screen.getByRole('status')).toHaveTextContent('Overlap 2 of 2')
    expect(
      screen.getByRole('heading', {
        name: 'Should Justice League International (1987) continue while Mister Miracle (2019) waits?',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use these choices' })).toBeDisabled()

    await user.click(screen.getByRole('radio', { name: /Keep the full chosen order/ }))
    rerender(
      {
        [MISTER_MIRACLE_OVERLAP.overlap_id]: 'continue_series',
        [SECOND_MISTER_MIRACLE_OVERLAP.overlap_id]: 'protect_order',
      },
      [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
    )
    await user.click(screen.getByRole('button', { name: 'Use these choices' }))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('closes without saving on Cancel and steps back to the prior series', async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog({
      overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
      choices: { [MISTER_MIRACLE_OVERLAP.overlap_id]: 'protect_order' },
    })

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Next series' }))
    expect(screen.getByRole('status')).toHaveTextContent('Overlap 2 of 2')
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('status')).toHaveTextContent('Overlap 1 of 2')
    expect(
      screen.getByRole('radio', { name: /Keep the full chosen order/ }),
    ).toHaveAttribute('aria-checked', 'true')
  })

  it('supports arrow-key selection inside the series radiogroup', async () => {
    const user = userEvent.setup()
    const { onChoose } = renderDialog()
    const first = screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ })
    first.focus()
    await user.keyboard('{ArrowDown}')
    expect(onChoose).toHaveBeenCalledWith(
      MISTER_MIRACLE_OVERLAP.overlap_id,
      'protect_order',
    )
  })

  it('keeps arrow-key navigation working after advancing to the next series', async () => {
    const user = userEvent.setup()
    const { onChoose, rerender } = renderDialog({
      overlaps: [MISTER_MIRACLE_OVERLAP, SECOND_MISTER_MIRACLE_OVERLAP],
    })

    await user.click(
      screen.getByRole('radio', { name: /Mister Miracle waits; JLI continues/ }),
    )
    rerender({ [MISTER_MIRACLE_OVERLAP.overlap_id]: 'continue_series' }, [
      MISTER_MIRACLE_OVERLAP,
      SECOND_MISTER_MIRACLE_OVERLAP,
    ])
    await user.click(screen.getByRole('button', { name: 'Next series' }))

    expect(screen.getByRole('status')).toHaveTextContent('Overlap 2 of 2')
    const secondFirst = screen.getByRole('radio', {
      name: /Mister Miracle waits; JLI continues/,
    })
    secondFirst.focus()
    await user.keyboard('{ArrowDown}')
    expect(onChoose).toHaveBeenCalledWith(
      SECOND_MISTER_MIRACLE_OVERLAP.overlap_id,
      'protect_order',
    )
  })

  it('never shows a questionnaire for a source without a genuine overlap', () => {
    render(
      <ReadingGraphOverlapDialog
        isOpen
        preview={withoutOverlap()}
        choices={{}}
        onChoose={vi.fn()}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'No overlapping series need a decision.',
    )
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
  })
})
