import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('dynamic import mock test', () => {
  let testModule: any;

  beforeEach(async () => {
    vi.mock('./test.module', () => ({
      myFunction: () => 'mocked implementation'
    }));
    
    testModule = await import('./test.module');
  });

  it('should use the mocked implementation', () => {
    expect(testModule.myFunction()).toBe('mocked implementation');
  });
});
