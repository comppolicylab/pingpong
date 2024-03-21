import { describe, it, expect } from 'vitest';
import purify from './purify';

describe('purify', () => {
  it('should add target blank and proper rel to links', () => {
    expect(purify.sanitize(`<a href="https://pingpong.local/">pingpong</a>`)).toBe(
      `<a href="https://pingpong.local/" target="_blank" rel="noopener noreferrer">pingpong</a>`
    );
  });

  it('should not add target blank and proper rel to non-links', () => {
    expect(purify.sanitize('<div>pingpong</div>')).toBe('<div>pingpong</div>');
  });
});
