import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('../hooks/useThread', () => ({}));
describe('test', () => {
  it('should pass', () => {
    expect(true).toBe(true);
  });
});
