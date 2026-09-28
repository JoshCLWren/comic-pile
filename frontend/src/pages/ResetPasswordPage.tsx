import type { FormEvent } from 'react'
import axios from 'axios'
import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../services/api'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSuccess, setIsSuccess] = useState(false)
  const [tokenValid, setTokenValid] = useState(true)

  useEffect(() => {
    if (!token) {
      setTokenValid(false)
      setError('Invalid or missing reset token.')
    }
  }, [token])

  const validateForm = () => {
    if (!password) {
      setError('Password is required')
      return false
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return false
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return false
    }
    return true
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')

    if (!token) {
      setError('Invalid or missing reset token.')
      return
    }

    if (!validateForm()) {
      return
    }

    setIsLoading(true)

    try {
      await authApi.resetPassword({ token, new_password: password })
      setIsSuccess(true)
    } catch (err: unknown) {
      if (axios.isAxiosError<{ detail?: string }>(err) && err.response?.data?.detail) {
        const detail = err.response.data.detail
        if (detail.includes('expired') || detail.includes('used') || detail.includes('superseded') || detail.includes('Invalid')) {
          setError('This reset link has expired or was already used. Please request a new one.')
        } else {
          setError(detail)
        }
      } else if (axios.isAxiosError(err) && err.response?.status === 400) {
        setError('This reset link has expired or was already used. Please request a new one.')
      } else {
        setError('Reset failed. Please try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  if (!tokenValid) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center space-y-2">
            <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">Reset Password</h1>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6 text-center">
            <div className="space-y-3">
              <div className="w-16 h-16 mx-auto bg-[var(--theme-danger)]/10 rounded-full flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--theme-danger)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <h2 className="text-xl font-bold text-[var(--theme-text-primary)]">Invalid Reset Link</h2>
              <p className="text-sm text-[var(--theme-text-muted)]">
                This password reset link is invalid, has expired, or has already been used.
              </p>
            </div>

            <div className="space-y-3 pt-4 border-t border-[var(--theme-border)]">
              <Link
                to="/forgot-password"
                className="block w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-sm font-bold text-stone-900 transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              >
                Request New Reset Link
              </Link>
              <Link
                to="/login"
                className="block w-full h-12 bg-transparent border border-[var(--theme-border)] hover:bg-[var(--theme-bg-page)] rounded-xl text-sm font-bold text-[var(--theme-text-primary)] transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              >
                Back to Sign In
              </Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (isSuccess) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center space-y-2">
            <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">Reset Password</h1>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6 text-center">
            <div className="space-y-3">
              <div className="w-16 h-16 mx-auto bg-[var(--theme-primary-action)]/10 rounded-full flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--theme-primary-action)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-xl font-bold text-[var(--theme-text-primary)]">Password Reset Successfully</h2>
              <p className="text-sm text-[var(--theme-text-muted)]">
                Your password has been updated. All existing sessions have been revoked.
              </p>
              <p className="text-xs text-[var(--theme-text-muted)]">
                Please sign in with your username and new password.
              </p>
            </div>

            <div className="space-y-3 pt-4 border-t border-[var(--theme-border)]">
              <Link
                to="/login"
                className="block w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-sm font-bold text-stone-900 transition-colors flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              >
                Sign In with New Password
              </Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">Reset Password</h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Enter your new password below. Minimum 6 characters.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium text-[var(--theme-text-muted)]">
                New Password
              </label>
              <input
                id="password"
                type="password"
                name="password"
                autoComplete="new-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full h-12 px-4 rounded-xl text-sm form-control"
                placeholder="Min 6 characters"
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="confirmPassword" className="text-sm font-medium text-[var(--theme-text-muted)]">
                Confirm New Password
              </label>
              <input
                id="confirmPassword"
                type="password"
                name="confirmPassword"
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full h-12 px-4 rounded-xl text-sm form-control"
                placeholder="Re-enter password"
                disabled={isLoading}
              />
            </div>
          </div>

          {error && (
            <div className="bg-[var(--theme-danger)]/10 border border-[var(--theme-danger)]/20 rounded-xl px-4 py-3">
              <p className="text-sm text-[var(--theme-danger)] font-medium">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-sm font-bold text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
          >
            {isLoading ? 'Resetting...' : 'Reset Password'}
          </button>
        </form>

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