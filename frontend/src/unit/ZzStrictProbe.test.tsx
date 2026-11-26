import { StrictMode, useEffect } from 'react'
import { act as reactAct } from 'react'
import { createRoot } from 'react-dom/client'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

async function flush() {
  await reactAct(async () => {
    await Promise.resolve()
  })
}

describe('strict effect probe', () => {
  it('RTL render', async () => {
    let setups = 0
    let cleanups = 0
    function Probe() {
      useEffect(() => {
        setups += 1
        return () => { cleanups += 1 }
      }, [])
      return null
    }
    render(<StrictMode><Probe /></StrictMode>)
    await flush()
    console.log('RTL_RENDER_PROBE', { setups, cleanups })
    expect(setups).toBeGreaterThanOrEqual(1)
  })

  it('createRoot inside react act', async () => {
    let setups = 0
    let cleanups = 0
    function Probe() {
      useEffect(() => {
        setups += 1
        return () => { cleanups += 1 }
      }, [])
      return null
    }
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await reactAct(async () => {
      root.render(<StrictMode><Probe /></StrictMode>)
    })
    console.log('CREATE_ROOT_ACT_PROBE', { setups, cleanups })
    root.unmount()
    expect(setups).toBeGreaterThanOrEqual(1)
  })

  it('createRoot no act', async () => {
    let setups = 0
    let cleanups = 0
    function Probe() {
      useEffect(() => {
        setups += 1
        return () => { cleanups += 1 }
      }, [])
      return null
    }
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    root.render(<StrictMode><Probe /></StrictMode>)
    await flush()
    console.log('CREATE_ROOT_PROBE', { setups, cleanups })
    root.unmount()
    expect(setups).toBeGreaterThanOrEqual(1)
  })
})
