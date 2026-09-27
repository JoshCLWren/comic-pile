import type { FormEvent } from 'react'
import axios from 'axios'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import { validateEmail } from '../utils/passwordValidation'

interface ForgotPasswordResponse {
  message: string
}

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSubmitted, setIsSubmitted] = useState(false)

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')

    if (!email.trim()) {
      setError('Email is required')
      return
    }
    if (!validateEmail(email)) {
      setError('Please enter a valid email address')
      return
    }

    setIsSubmitting(true)

    try {
      await api.post<ForgotPasswordResponse, { email: string }>('/v1/auth/forgot-password', {
        email: email.trim(),
      })
      setIsSubmitted(true)
    } catch (err: unknown) {
      if (axios.isAxiosError<{ detail?: string }>(err) && err.response?.data?.detail) {
        setError(err.response.data.detail)
      } else if (axios.isAxiosError(err) && err.response?.status === 429) {
        setError('Too many requests. Please try again later.')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isSubmitted) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-primary-action)]">Comic Pile · Roll to read. Rotate your stack.</p>
            <h1 className="text-3xl font-black tracking-tighter text-glow uppercase">Check Your Email</h1>
            <p className="text-sm text-[var(--theme-text-muted)]">
              If an account exists for that email, a reset link has been sent. It will expire in 30 minutes.
            </p>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 text-center space-y-6">
            <div className="space-y-4">
              <p className="text-sm text-[var(--theme-text-muted)]">
                Didn't receive it? Check your spam folder or request another reset link.
              </p>
              <Link
                to="/forgot-password"
                className="inline-block w-full h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] flex items-center justify-center"
              >
                Request another reset link
              </Link>
            </div>
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
          <h1 className="text-3xl font-black tracking-tighter text-glow uppercase">Forgot Password</h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Enter the email address on your account and we'll send you a reset link.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-6">
          <div className="space-y-2">
            <label htmlFor="email" className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
              Email Address
            </label>
            <p className="text-xs text-[var(--theme-text-muted)]">This is the email associated with your Comic Pile account.</p>
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
            />
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
            {isSubmitting ? 'Sending...' : 'Send Reset Link'}
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
