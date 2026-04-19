import type { FormEvent } from 'react'
import axios from 'axios'
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api from '../services/api'
import type { AuthTokens } from '../types'
import { useAuth } from '../App'

export default function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const navigate = useNavigate()

  const validateForm = () => {
    if (!username.trim()) {
      setError('Username is required')
      return false
    }
    if (!password.trim()) {
      setError('Password is required')
      return false
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters')
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
      const response = await api.post<AuthTokens, { username: string; password: string }>('/auth/login', {
        username: username.trim(),
        password,
      })
      await login(response.access_token)
      navigate('/')
    } catch (err: unknown) {
      if (axios.isAxiosError<{ detail?: string }>(err) && err.response?.data?.detail) {
        setError(err.response.data.detail)
      } else if (axios.isAxiosError(err) && err.response?.status === 401) {
        setError('Invalid username or password')
      } else {
        setError('Login failed. Please try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">Welcome Back</h1>
          <p className="text-sm text-stone-400">Sign in to continue your journey</p>
        </div>

          <form onSubmit={handleSubmit} className="glass-card rounded-2xl p-6 space-y-6">
           <div className="space-y-4">
             <div className="space-y-2">
               <label htmlFor="username" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                 Username
               </label>
               <input
                 id="username"
                 type="text"
                 name="username"
                 autoComplete="username"
                 required
                 value={username}
                 onChange={(e) => setUsername(e.target.value)}
                 className="w-full h-12 px-4 bg-white/5 border border-white/20 rounded-xl text-sm text-stone-200 placeholder-stone-500 focus:outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-500/30 transition-colors"
                 placeholder="Enter your username"
               />
             </div>

            <div className="space-y-2">
              <label htmlFor="password" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                Password
              </label>
              <input
                id="password"
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full h-12 px-4 bg-white/5 border border-white/20 rounded-xl text-sm text-stone-200 placeholder-stone-500 focus:outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-500/30 transition-colors"
                placeholder="••••••••"
              />
            </div>
          </div>

          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
              <p className="text-sm text-red-400 font-medium">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full h-12 bg-amber-600 hover:bg-amber-500 disabled:bg-amber-600/50 disabled:cursor-not-allowed rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 focus:ring-offset-[#1a1410]"
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div className="text-center">
          <p className="text-sm text-stone-400">
            Don't have an account?{' '}
            <Link to="/register" className="text-amber-500 hover:text-amber-400 font-bold transition-colors">
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
