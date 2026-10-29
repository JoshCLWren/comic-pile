import { renderHook, act } from '@testing-library/react-hooks';
import { useRollActions } from '../../src/pages/RollPage/useRollActions';

describe('useRollActions die mode handling', () => {
  it('sets automatic die and clears manual die on handleClearManualDie', async () => {
    const setCurrentDie = jest.fn();
    const clearManualDieMutation = jest.fn().mockResolvedValue(undefined);
    const mutations = { clearManualDieMutation };
    const state = { setCurrentDie };
    const bootstrap = { current_die: 20 };
    const refetchBootstrap = () => Promise.resolve();

    const { result } = renderHook(() => useRollActions({
      state,
      bootstrap,
      rollPool: [],
      navigate: () => {},
      mutations,
      refetchBootstrap,
      enterRatingView: () => {},
      onSnoozeRefreshFailed: () => {},
      onSkipRefreshFailed: () => {},
    }));

    // Mock setCurrentDie
    result.current.state.setCurrentDie = setCurrentDie;

    await act(async () => {
      await result.current.handleClearManualDie();
    });

    expect(setCurrentDie).toHaveBeenCalledWith(6);
    expect(clearManualDieMutation).toHaveBeenCalled();
  });

  it('handles delayed clearManualDieMutation without error', async () => {
    const setCurrentDie = jest.fn();
    const clearManualDieMutation = jest.fn().mockImplementation(() => new Promise(resolve => {
      setTimeout(() => resolve(undefined), 100);
    }));
    const mutations = { clearManualDieMutation };
    const state = { setCurrentDie };
    const bootstrap = { current_die: 20 };
    const refetchBootstrap = () => Promise.resolve();

    const { result } = renderHook(() => useRollActions({
      state,
      bootstrap,
      rollPool: [],
      navigate: () => {},
      mutations,
      refetchBootstrap,
      enterRatingView: () => {},
      onSnoozeRefreshFailed: () => {},
      onSkipRefreshFailed: () => {},
    }));

    result.current.state.setCurrentDie = setCurrentDie;

    await act(async () => {
      await result.current.handleClearManualDie();
    });

    expect(setCurrentDie).toHaveBeenCalledWith(6);
    // Wait for the delayed mutation to resolve
    await new Promise(resolve => setTimeout(resolve, 110));
    expect(clearManualDieMutation).toHaveBeenCalled();
  });
});