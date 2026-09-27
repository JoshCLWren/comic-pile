export const MIN_PASSWORD_LENGTH = 6

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidPassword(password: string): boolean {
  return password.trim().length >= MIN_PASSWORD_LENGTH
}

export function validatePassword(password: string): string | null {
  if (!password.trim()) {
    return 'Password is required'
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
  }
  return null
}

export function isValidEmail(email: string): boolean {
  return EMAIL_REGEX.test(email.trim())
}

export function validateEmail(email: string): string | null {
  if (!email.trim()) {
    return 'Email is required'
  }
  if (!isValidEmail(email)) {
    return 'Please enter a valid email address'
  }
  return null
}
