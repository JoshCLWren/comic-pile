import type { FormEvent } from 'react'
import axios from 'axios'
import { useState, useEffect } from 'react'
import { useNavigate, Link, useLocation } from 'react-router-dom'
import api from '../services/api'
import { validatePassword, MIN_PASSWORD_LENGTH } from '../utils/passwordValidation'

const TOKEN_EXPIRED_MESSAGES = [
  'expired',
  'invalid or expired',
  'already been used',
  'invalid',
]

interface ResetPasswordResponse {
  message: string
}

function extractTokenFromSearch(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  return params.get('token')
}

export default function ResetPasswordPage() {
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const t = extractTokenFromSearch()
    setToken(t)
    if (!t) {
      setError('This reset link is invalid or has expired. Please request a new password reset link.')
    }
  }, [location.search, setToken])

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')

    if (!token) {
      return
    }

    if (!newPassword.trim()) {
      setError('Password is required')
      return
    }
    const passwordError = validatePassword(newPassword)
    if (passwordError) {
      setError(passwordError)
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setIsSubmitting(true)

    try {
      await api.post<ResetPasswordResponse, { token: string; new_password: string }>(
        '/v1/auth/reset-password',
        { token, new_password: newPassword },
      )
      navigate('/login', {
        state: { passwordReset: true },
      })
    } catch (err: unknown) {
      if (axios.isAxiosError<{ detail?: string }>(err) && err.response?.data?.detail) {
        const detail = err.response.data.detail
        if (err.response.status === 400 && TOKEN_EXPIRED_MESSAGES.some(msg => detail.toLowerCase().includes(msg))) {
          setError('This reset link has expired, been used, or is invalid. Please request a new reset link from the login page.')
        } else {
          setError(detail)
        }
      } else if (axios.isAxiosError(err) && err.response?.status === 429) {
        setError('Too many attempts. Please try again later.')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-primary-action)]">Comic Pile · Roll to read. Rotate your stack.</p>
            <h1 className="text-3xl font-black tracking-tighter text-glow uppercase">Invalid Reset Link</h1>
            <p className="text-sm text-[var(--theme-text-muted)]">
              {error || 'This reset link is missing or invalid.'}
            </p>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 text-center space-y-4">
            <Link
              to="/forgot-password"
              className="inline-block w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] flex items-center justify-center"
            >
              Request a new reset link
            </Link>
          </div>

          <div className="text-center">
            <p className="text-sm text-[var(--theme-text-muted)]">
              <Link to="/login" className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity">
                Back to login
              </Link>
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-primary-action)]">Comic Pile · Roll to read. Rotate your stack.</p>
          <h1 className="text-3xl font-black tracking-tighter text-glow uppercase">Reset Password</h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Choose a new password for your account.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6" data-testid="reset-password-form">
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="newPassword" className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
                New Password
              </label>
              <input
                id="newPassword"
                type="password"
                name="newPassword"
                autoComplete="new-password"
                required
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full h-12 px-4 rounded-xl text-sm form-control"
                placeholder={`Min ${MIN_PASSWORD_LENGTH} characters`}
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="confirmPassword" className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
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
                placeholder="Re-enter new password"
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
            disabled={isSubmitting}
            className="w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
          >
            {isSubmitting ? 'Resetting...' : 'Reset Password'}
          </button>
        </form>

        <div className="text-center">
          <p className="text-sm text-[var(--theme-text-muted)]">
            <Link to="/login" className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity">
              Back to login
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
