import { beforeEach, describe, expect, it, vi } from 'vitest';
const mockFn = vi['mock'];
mockFn('./test-module', () => ({}));
describe('test', () => {
  it('should pass', () => {
    expect(true).toBe(true);
  });
});
