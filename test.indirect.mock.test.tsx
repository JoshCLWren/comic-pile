import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as testModule from './test.module';

const mockFn = vi['mock'];
mockFn('./test.module', () => ({
  myFunction: () => 'mocked implementation'
}));

describe('indirect mock test', () => {
  it('should use the mocked implementation', () => {
    expect(testModule.myFunction()).toBe('mocked implementation');
  });
});
