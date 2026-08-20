import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollPrerequisiteSwitch } from '../hooks/useRollPrerequisiteSwitch'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import {
  fetchAndPublishRollBootstrap,
  isAmbiguousNetworkFailure,
} from '../hooks/rollMutationReconciliation'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    switchPrerequisite: vi.fn(),
  },
}))

vi.mock('../hooks/rollMutationReconciliation', () => ({
  fetchAndPublishRollBootstrap: vi.fn(),
  isAmbiguousNetworkFailure: vi.fn(),
}))

const mockedSwitchPrerequisite = vi.mocked(rollBootstrapApi.switchPrerequisite)
const mockedFetchAndPublishRollBootstrap = vi.mocked(fetchAndPublishRollBootstrap)
const mockedIsAmbiguousNetworkFailure = vi.mocked(isAmbiguousNetworkFailure)

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchAndPublishRollBootstrap.mockResolvedValue({} as never)
  mockedIsAmbiguousNetworkFailure.mockReturnValue(false)
})

describe('useRollPrerequisiteSwitch', () => {
  it('returns pending state when switching', async () => {
    mockedSwitchPrerequisite.mockResolvedValue({} as never)

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    expect(result.current.isPending).toBe(false)
    expect(result.current.errorMessage).toBe(null)

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(mockedSwitchPrerequisite).toHaveBeenCalledWith({ node_type: 'issue', node_id: 42 })
    expect(mockedFetchAndPublishRollBootstrap).toHaveBeenCalled()
    expect(result.current.isPending).toBe(false)
  })

  it('clears error message when switching', async () => {
    mockedSwitchPrerequisite.mockResolvedValue({} as never)

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(result.current.errorMessage).toBe(null)
  })

  it('does not switch when already pending', async () => {
    mockedSwitchPrerequisite.mockImplementation(() => {
      return new Promise(() => {})
    })

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    const switchPromise = act(async () => {
      await result.current.switchIssue(42)
    })

    expect(mockedSwitchPrerequisite).not.toHaveBeenCalled()
  })

  it('returns error message when switch fails but bootstrap refresh succeeds', async () => {
    const error = new Error('switch failed')
    mockedSwitchPrerequisite.mockRejectedValue(error)
    mockedIsAmbiguousNetworkFailure.mockReturnValue(false)
    mockedFetchAndPublishRollBootstrap.mockResolvedValue({} as never)

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(mockedSwitchPrerequisite).toHaveBeenCalledWith({ node_type: 'issue', node_id: 42 })
    expect(mockedFetchAndPublishRollBootstrap).toHaveBeenCalled()
    expect(result.current.errorMessage).toContain('switched')
    expect(result.current.errorMessage).toContain('refreshed')
  })

  it('returns ambiguous error when network failure occurs', async () => {
    const error = new Error('Network Error')
    mockedSwitchPrerequisite.mockRejectedValue(error)
    mockedIsAmbiguousNetworkFailure.mockReturnValue(true)
    mockedFetchAndPublishRollBootstrap.mockResolvedValue({} as never)

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(result.current.errorMessage).toContain('could not confirm whether the roll switched')
    expect(result.current.isPending).toBe(false)
  })

  it('returns error when bootstrap refresh also fails with ambiguous network failure', async () => {
    const error = new Error('Network Error')
    mockedSwitchPrerequisite.mockRejectedValue(error)
    mockedIsAmbiguousNetworkFailure.mockReturnValue(true)
    mockedFetchAndPublishRollBootstrap.mockRejectedValue(new Error('refresh failed'))

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(result.current.errorMessage).toContain('could not confirm whether the roll switched or refresh recovery guidance')
  })

  it('resets pending state after successful switch', async () => {
    mockedSwitchPrerequisite.mockResolvedValue({} as never)

    const { result } = renderHook(() => useRollPrerequisiteSwitch())

    await act(async () => {
      await result.current.switchIssue(42)
    })

    expect(result.current.isPending).toBe(false)
  })
})