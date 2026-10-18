import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('dynamic mock test', () => {
  let testModule: any;

  beforeEach(() => {
    vi.mock('./test.module', () => ({
      myFunction: () => 'mocked implementation'
    }));
    testModule = require('./test.module');
  });

  it('should use the mocked implementation', () => {
    expect(testModule.myFunction()).toBe('mocked implementation');
  });
});
