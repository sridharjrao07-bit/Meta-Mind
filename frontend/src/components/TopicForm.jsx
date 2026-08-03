import { useState } from 'react'
import { createTopic } from '../api.js'

export default function TopicForm({ token, onCreated }) {
  const [name, setName] = useState('')
  const [course, setCourse] = useState('')
  const [referenceNotes, setReferenceNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const topic = await createTopic(token, { name, course: course || null, reference_notes: referenceNotes || null })
      setName('')
      setCourse('')
      setReferenceNotes('')
      onCreated(topic)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card">
      <div className="card-title">New Topic</div>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="topic-name">Topic name</label>
          <input
            id="topic-name"
            type="text"
            placeholder="e.g. Photosynthesis"
            value={name}
            onChange={e => setName(e.target.value)}
            required
            maxLength={200}
          />
        </div>
        <div className="form-group">
          <label htmlFor="topic-course">Course (optional)</label>
          <input
            id="topic-course"
            type="text"
            placeholder="e.g. Bio 101"
            value={course}
            onChange={e => setCourse(e.target.value)}
            maxLength={200}
          />
        </div>
        <div className="form-group">
          <label htmlFor="topic-notes">Reference Notes (Ground truth for AI)</label>
          <textarea
            id="topic-notes"
            placeholder="Paste verified facts or course notes here so the agent grounds its challenges accurately..."
            value={referenceNotes}
            onChange={e => setReferenceNotes(e.target.value)}
            maxLength={2000}
            style={{ minHeight: '80px' }}
          />
        </div>

        {error && <div className="error-msg">{error}</div>}

        <button
          id="create-topic-btn"
          className="btn btn-primary"
          type="submit"
          disabled={loading}
          style={{ marginTop: '0.75rem' }}
        >
          {loading ? <span className="spinner" /> : 'Add Topic'}
        </button>
      </form>
    </div>
  )
}
