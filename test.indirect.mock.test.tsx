import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as testModule from './test.module';

vi.mock('./test.module', () => ({
  myFunction: () => 'mocked implementation'
}));

describe('indirect mock test', () => {
  it('should use the mocked implementation', () => {
    expect(testModule.myFunction()).toBe('mocked implementation');
  });
});
