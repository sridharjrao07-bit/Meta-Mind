import { useState, useEffect } from 'react'
import AuthPage from './components/AuthPage.jsx'
import Dashboard from './components/Dashboard.jsx'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { refreshSession } from './api.js'

const TOKEN_KEY   = 'metamind_token'
const USER_KEY    = 'metamind_user'

/** A valid JWT has exactly 3 dot-separated base64 segments. */
function isValidJwt(t) {
  return typeof t === 'string' && t.split('.').length === 3
}

function loadStoredToken() {
  const t = localStorage.getItem(TOKEN_KEY)
  if (!isValidJwt(t)) {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    return null
  }
  return t
}

export default function App() {
  const [token, setToken] = useState(() => loadStoredToken())
  const [user, setUser]   = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null }
  })

  // On mount: silently refresh if a refresh_token exists but the access_token
  // may have expired (e.g. the tab was closed for > 1 hour).
  useEffect(() => {
    if (!token) return          // not logged in — nothing to refresh
    refreshSession().then(newToken => {
      if (newToken && newToken !== token) setToken(newToken)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleAuth(accessToken, userData) {
    localStorage.setItem(TOKEN_KEY, accessToken)
    localStorage.setItem(USER_KEY, JSON.stringify(userData))
    setToken(accessToken)
    setUser(userData)
  }

  function handleSignOut() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setToken(null)
    setUser(null)
  }

  if (!token) {
    return (
      <ThemeProvider>
        <AuthPage onAuth={handleAuth} />
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider>
      <Dashboard
        token={token}
        user={user}
        onSignOut={handleSignOut}
      />
    </ThemeProvider>
  )
}
