import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as testModule from './test-module';
vi.mocked(testModule);
describe('test', () => {
  it('should pass', () => {
    expect(true).toBe(true);
  });
});
