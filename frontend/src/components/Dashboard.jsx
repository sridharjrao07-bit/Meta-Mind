import { useEffect, useState } from 'react'
import { getTopics, getDashboard, getStreaks, getAchievements } from '../api.js'
import { useTheme } from '../context/ThemeContext.jsx'
import { getCopy } from '../Dictionary.js'
import TopicForm from './TopicForm.jsx'
import DebateSession from './DebateSession.jsx'

export default function Dashboard({ token, user, onSignOut }) {
  const [view, setView] = useState('topics')          // topics | debate
  const [topics, setTopics] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [streaks, setStreaks] = useState(null)
  const [achievements, setAchievements] = useState([])
  const { mode, setMode } = useTheme()
  const [selectedTopic, setSelectedTopic] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoading(true)
    setError('')
    try {
      const [topicData, dashData, streakData, achData] = await Promise.all([
        getTopics(token),
        getDashboard(token),
        getStreaks(token),
        getAchievements(token),
      ])
      setTopics(topicData)
      setDashboard(dashData)
      setStreaks(streakData)
      setAchievements(achData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function handleTopicCreated(topic) {
    setTopics(prev => [topic, ...prev])
    setShowForm(false)
  }

  function handleSelectTopic(topic) {
    setSelectedTopic(topic)
    setView('debate')
  }

  function handleBackToTopics() {
    setView('topics')
    setSelectedTopic(null)
    loadAll()  // refresh mastery scores after a round
  }

  // ── Debate view ──
  if (view === 'debate' && selectedTopic) {
    return (
      <div className="app-shell">
        <header className="topbar">
          <div className="topbar-brand">MetaMind</div>
          <div className="topbar-actions">
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              {user?.email}
            </span>
            <select 
              value={mode} 
              onChange={e => setMode(e.target.value)} 
              style={{ padding: '0.3rem', width: 'auto', background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
            >
              <option value="adult">{getCopy('adult', 'modeSelectorText')}</option>
              <option value="teen">{getCopy('teen', 'modeSelectorText')}</option>
              <option value="kids">{getCopy('kids', 'modeSelectorText')}</option>
            </select>
            <button
              id="signout-btn"
              className="btn btn-secondary btn-sm"
              onClick={onSignOut}
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="main-content">
          <DebateSession
            token={token}
            topic={selectedTopic}
            onBack={handleBackToTopics}
          />
        </main>
      </div>
    )
  }

  // ── Topics / Dashboard view ──
  const dueCount = dashboard?.due_today?.length ?? 0

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">MetaMind</div>
        <div className="topbar-actions">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {user?.email}
          </span>
          <select 
            value={mode} 
            onChange={e => setMode(e.target.value)} 
            style={{ padding: '0.3rem', width: 'auto', background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
          >
            <option value="adult">{getCopy('adult', 'modeSelectorText')}</option>
            <option value="teen">{getCopy('teen', 'modeSelectorText')}</option>
            <option value="kids">{getCopy('kids', 'modeSelectorText')}</option>
          </select>
          <button
            id="signout-btn"
            className="btn btn-secondary btn-sm"
            onClick={onSignOut}
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="main-content">
        {/* ── Gamification Stats ── */}
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
          <div className="card" style={{ flex: 1, minWidth: '150px', marginBottom: 0 }}>
            <div className="card-title">{getCopy(mode, 'streakLabel')}</div>
            <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--accent)' }}>
              🔥 {streaks?.current_streak || 0}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              {getCopy(mode, 'freezeTokenLabel')}: {streaks?.freeze_tokens || 0}
            </div>
          </div>
          
          <div className="card" style={{ flex: '2', minWidth: '250px', marginBottom: 0 }}>
            <div className="card-title">Achievements</div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {achievements.length === 0 ? (
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No achievements yet</span>
              ) : (
                achievements.map(a => (
                  <span key={a.id} title={a.type} style={{
                    display: 'inline-block', padding: '0.3rem 0.6rem',
                    background: 'var(--accent-glow)', color: 'var(--accent)',
                    borderRadius: 'var(--radius-sm)', fontSize: '0.75rem', fontWeight: 600
                  }}>
                    {a.type === 'Perfect Score' ? '⭐' : a.type === 'First Debate Completed' ? '🏆' : a.type === 'Comeback' ? '🔄' : '🔥'} {a.type}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Due today banner ── */}
        {dueCount > 0 && (
          <div className="info-msg" style={{ marginBottom: '1.5rem', marginTop: 0 }}>
            📅 <strong>{dueCount}</strong> {getCopy(mode, 'dueToday')}.
          </div>
        )}

        {/* ── Topics list ── */}
        <div className="section-header">
          <h2 className="section-title">Topics</h2>
          <button
            id="new-topic-btn"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowForm(f => !f)}
          >
            {showForm ? '✕ Cancel' : '+ New Topic'}
          </button>
        </div>

        {showForm && (
          <TopicForm token={token} onCreated={handleTopicCreated} />
        )}

        {error && <div className="error-msg">{error}</div>}

        {loading && (
          <div className="empty">
            <span className="spinner" style={{ borderTopColor: 'var(--accent)' }} />
          </div>
        )}

        {!loading && topics.length === 0 && (
          <div className="empty">
            No topics yet. Add one above to start your first debate round.
          </div>
        )}

        {!loading && topics.map(topic => {
          const mastery = dashboard?.mastery?.find(m => m.topic_id === topic.id)
          const isDue = dashboard?.due_today?.some(m => m.topic_id === topic.id)

          return (
            <div
              key={topic.id}
              id={`topic-${topic.id}`}
              className="topic-item"
              onClick={() => handleSelectTopic(topic)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && handleSelectTopic(topic)}
            >
              <div>
                <div className="topic-name">
                  {isDue && <span style={{ color: 'var(--warning)', marginRight: '0.4rem' }}>●</span>}
                  {topic.name}
                </div>
                {topic.course && (
                  <div className="topic-course">{topic.course}</div>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.2rem' }}>
                {mastery?.current_score != null ? (
                  <div className="topic-score">
                    {(mastery.current_score * 100).toFixed(0)}%
                  </div>
                ) : (
                  <div className="topic-score" style={{ color: 'var(--text-muted)' }}>
                    —
                  </div>
                )}
                {mastery?.total_attempts > 0 && (
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {mastery.total_attempts} round{mastery.total_attempts > 1 ? 's' : ''}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </main>
    </div>
  )
}
