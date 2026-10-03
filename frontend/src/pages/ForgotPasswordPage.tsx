import type { FormEvent } from 'react'
import axios from 'axios'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi } from '../services/api-auth'
import { isNonEmptyString } from '../utils/runtimeChecks'

// FastAPI reports a successful-but-pessimistic 200 for unknown accounts, so any
// error here is transport-level. A 422 carries a structured `detail` list
// instead of a string, which must never be rendered as a React child.
function readErrorMessage(err: unknown): string | null {
  if (!axios.isAxiosError<{ detail?: unknown }>(err)) {
    return null
  }
  return isNonEmptyString(err.response?.data?.detail) ? err.response.data.detail : null
}

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)

  const validateEmail = (emailValue: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailValue)
  }

  const validateForm = () => {
    if (!email.trim()) {
      setError('Email is required')
      return false
    }
    if (!validateEmail(email)) {
      setError('Please enter a valid email address')
      return false
    }
    return true
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')

    if (!validateForm()) {
      return
    }

    setIsLoading(true)

    try {
      await authApi.forgotPassword({ email: email.trim() })
      setIsSubmitted(true)
    } catch (err: unknown) {
      const detail = readErrorMessage(err)
      if (detail) {
        setError(detail)
      } else if (axios.isAxiosError(err) && err.response?.status === 429) {
        setError('Too many requests. Please wait a moment and try again.')
      } else {
        setError('Request failed. Please try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">Forgot Password</h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Enter your account email and we'll send a reset link if an account exists.
          </p>
        </div>

        {!isSubmitted ? (
          <form noValidate onSubmit={handleSubmit} className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6">
            <div className="space-y-4">
              <div className="space-y-2">
                <label htmlFor="email" className="text-sm font-medium text-[var(--theme-text-muted)]">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  name="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-12 px-4 rounded-xl text-sm form-control"
                  placeholder="you@example.com"
                  disabled={isLoading}
                />
              </div>
            </div>

            {error && (
              <div
                role="alert"
                className="bg-[var(--theme-danger)]/10 border border-[var(--theme-danger)]/20 rounded-xl px-4 py-3"
              >
                <p className="text-sm text-[var(--theme-danger)] font-medium">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-sm font-bold text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
            >
              {isLoading ? 'Sending...' : 'Send Reset Link'}
            </button>
          </form>
        ) : (
          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6 text-center">
            <div className="space-y-3">
              <div className="w-16 h-16 mx-auto bg-[var(--theme-primary-action)]/10 rounded-full flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--theme-primary-action)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-xl font-bold text-[var(--theme-text-primary)]">Check your email</h2>
              <p className="text-sm text-[var(--theme-text-muted)]">
                If an account exists for <strong>{email}</strong>, a password reset link has been sent.
              </p>
              <p className="text-xs text-[var(--theme-text-muted)]">
                The link expires in 30 minutes. If you don't see the email, check your spam folder.
              </p>
            </div>

            <div className="space-y-3 pt-4 border-t border-[var(--theme-border)]">
              <Link
                to="/login"
                className="block w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-sm font-bold text-stone-900 transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              >
                Back to Sign In
              </Link>
              <p className="text-xs text-[var(--theme-text-muted)]">
                Remember your password?{' '}
                <Link to="/login" className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity">
                  Sign in
                </Link>
              </p>
            </div>
          </div>
        )}

        <div className="text-center">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Back to{' '}
            <Link to="/login" className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity">
              Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
