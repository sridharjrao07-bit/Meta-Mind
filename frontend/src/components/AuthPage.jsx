import { useState } from 'react'
import { signIn, signUp } from '../api.js'

export default function AuthPage({ onAuth }) {
  const [tab, setTab] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    setLoading(true)
    try {
      if (tab === 'signup') {
        const data = await signUp(email, password)
        // Supabase returns access_token at top level OR inside session depending on version
        const token = data.access_token ?? data.session?.access_token
        if (token && token.split('.').length === 3) {
          onAuth(token, data.user ?? data.session?.user)
        } else {
          // Email confirmation required — no session yet
          setInfo('Check your email to confirm your account, then sign in.')
        }
      } else {
        const data = await signIn(email, password)
        const token = data.access_token ?? data.session?.access_token
        if (!token || token.split('.').length !== 3) {
          throw new Error('Sign in succeeded but no valid session token was returned. Check Supabase auth settings.')
        }
        onAuth(token, data.user ?? data.session?.user)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-box">
        <div className="auth-logo">MetaMind</div>
        <p className="auth-tagline">
          Understand, don't just recall. Explain. Defend. Master.
        </p>

        <div className="auth-tabs">
          <button
            id="tab-login"
            className={`auth-tab ${tab === 'login' ? 'active' : ''}`}
            onClick={() => { setTab('login'); setError(''); setInfo('') }}
          >
            Sign In
          </button>
          <button
            id="tab-signup"
            className={`auth-tab ${tab === 'signup' ? 'active' : ''}`}
            onClick={() => { setTab('signup'); setError(''); setInfo('') }}
          >
            Sign Up
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>
          <div className="form-group">
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              placeholder={tab === 'signup' ? 'At least 6 characters' : '••••••••'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete={tab === 'signup' ? 'new-password' : 'current-password'}
            />
          </div>

          {error && <div className="error-msg">{error}</div>}
          {info  && <div className="info-msg">{info}</div>}

          <button
            id="auth-submit-btn"
            className="btn btn-primary"
            type="submit"
            disabled={loading}
            style={{ marginTop: '1.25rem' }}
          >
            {loading
              ? <span className="spinner" />
              : tab === 'signup' ? 'Create Account' : 'Sign In'
            }
          </button>
        </form>
      </div>
    </div>
  )
}
