import { describe, it, expect } from 'vitest';
import {
  MIN_PASSWORD_LENGTH,
  isValidPassword,
  validatePassword,
  isValidEmail,
  validateEmail,
} from '../utils/passwordValidation';

describe('passwordValidation', () => {
  describe('MIN_PASSWORD_LENGTH', () => {
    it('should be 6', () => {
      expect(MIN_PASSWORD_LENGTH).toBe(6);
    });
  });

  describe('isValidPassword', () => {
    it('returns true for password meeting minimum length', () => {
      expect(isValidPassword('abcdef')).toBe(true);
      expect(isValidPassword('Password1!')).toBe(true);
      expect(isValidPassword('123456')).toBe(true);
    });

    it('returns false for password shorter than minimum length', () => {
      expect(isValidPassword('abcde')).toBe(false);
      expect(isValidPassword('')).toBe(false);
      expect(isValidPassword('   ')).toBe(false);
    });

    it('trims whitespace before checking length', () => {
      expect(isValidPassword('  abcdef  ')).toBe(true);
      expect(isValidPassword('  abcde  ')).toBe(false);
    });
  });

  describe('validatePassword', () => {
    it('returns null for valid password', () => {
      expect(validatePassword('abcdef')).toBeNull();
      expect(validatePassword('Password1!')).toBeNull();
    });

    it('returns error for empty password', () => {
      expect(validatePassword('')).toBe('Password is required');
      expect(validatePassword('   ')).toBe('Password is required');
    });

    it('returns error for password shorter than minimum length', () => {
      expect(validatePassword('abcde')).toBe('Password must be at least 6 characters');
    });

    it('trims for empty check but uses raw length for min check', () => {
      expect(validatePassword('  abcdef  ')).toBeNull();
      // '  abcde  ' has length 9 (including spaces) so passes min length
      expect(validatePassword('  abcde  ')).toBeNull();
    });
  });

  describe('isValidEmail', () => {
    it('returns true for valid email addresses', () => {
      expect(isValidEmail('user@example.com')).toBe(true);
      expect(isValidEmail('test.user@domain.org')).toBe(true);
      expect(isValidEmail('user+tag@example.co.uk')).toBe(true);
    });

    it('returns false for invalid email addresses', () => {
      expect(isValidEmail('invalid')).toBe(false);
      expect(isValidEmail('missing@domain')).toBe(false);
      expect(isValidEmail('@nodomain.com')).toBe(false);
      expect(isValidEmail('noatsign.com')).toBe(false);
      expect(isValidEmail('')).toBe(false);
      expect(isValidEmail('   ')).toBe(false);
    });

    it('trims whitespace before validation', () => {
      expect(isValidEmail('  user@example.com  ')).toBe(true);
      expect(isValidEmail('  invalid  ')).toBe(false);
    });
  });

  describe('validateEmail', () => {
    it('returns null for valid email', () => {
      expect(validateEmail('user@example.com')).toBeNull();
      expect(validateEmail('  test@domain.org  ')).toBeNull();
    });

    it('returns error for empty email', () => {
      expect(validateEmail('')).toBe('Email is required');
      expect(validateEmail('   ')).toBe('Email is required');
    });

    it('returns error for invalid email format', () => {
      expect(validateEmail('invalid')).toBe('Please enter a valid email address');
      expect(validateEmail('missing@domain')).toBe('Please enter a valid email address');
    });
  });
});