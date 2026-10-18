import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('dynamic mock test', () => {
  let testModule: any;

  beforeEach(() => {
    const mockFn = vi['mock'];
    mockFn('./test.module', () => ({
      myFunction: () => 'mocked implementation'
    }));
    
    // Import after mocking
    testModule = require('./test.module');
  });

  it('should use the mocked implementation', () => {
    expect(testModule.myFunction()).toBe('mocked implementation');
  });
});
