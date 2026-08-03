import { useEffect, useState } from 'react'
import { getTopics, getDashboard } from '../api.js'
import TopicForm from './TopicForm.jsx'
import DebateSession from './DebateSession.jsx'

export default function Dashboard({ token, user, onSignOut }) {
  const [view, setView] = useState('topics')          // topics | debate
  const [topics, setTopics] = useState([])
  const [dashboard, setDashboard] = useState(null)
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
      const [topicData, dashData] = await Promise.all([
        getTopics(token),
        getDashboard(token),
      ])
      setTopics(topicData)
      setDashboard(dashData)
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
        {/* ── Due today banner ── */}
        {dueCount > 0 && (
          <div className="info-msg" style={{ marginBottom: '1.5rem', marginTop: 0 }}>
            📅 <strong>{dueCount} topic{dueCount > 1 ? 's' : ''}</strong> due for review today.
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
