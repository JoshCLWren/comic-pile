import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('./test-module', () => ({}));
describe('test', () => {
  it('should pass', () => {
    expect(true).toBe(true);
  });
});
