import { StrictMode, useEffect } from 'react'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

describe('temp StrictMode effect probe', () => {
  it('counts setups and cleanups', () => {
    let setups = 0
    let cleanups = 0
    function Probe() {
      useEffect(() => {
        setups += 1
        return () => {
          cleanups += 1
        }
      }, [])
      return null
    }
    render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    )
    console.log('STRICT_PROBE', { setups, cleanups })
    expect(setups).toBeGreaterThanOrEqual(1)
  })
})
