/**
 * DebateSession — Phase 2 UI loop.
 *
 * State machine:
 *   explain → challenging (waiting for AI) → challenge_shown
 *   → rebutting (waiting for AI) → scored → compress → (reset / loop again)
 *
 * Phase 2 additions:
 *   - Confidence slider (predictedScore + sliderTouched) sent with explanation
 *   - Calibration chip shown after scoring when slider was touched
 *   - Staggered scoring narration (criteria → verdict → score, ~200ms per step)
 *   - Compression step after scoring (skippable, same-page reset on skip)
 *
 * The four-step narration (ACKNOWLEDGE → LOCATE → CLASSIFY → PRESENT) and
 * five-step scoring (CRITERIA → VERDICT → SCORE → FAILURE MODE → WEAK POINT)
 * are displayed as distinct, sequentially animated steps — never a single
 * wall of text. This is the core Section 11 "not blindsided" principle.
 */

import { useState } from 'react'
import { debateStart, debateRespond, debateCompress, flagDebateRound } from '../api.js'
import { useTheme } from '../context/ThemeContext.jsx'
import { getCopy } from '../Dictionary.js'

const STEP_LABELS = {
  ack: 'Acknowledge',
  loc: 'Locate',
  cls: 'Classify',
  chl: 'Challenge',
  cri: 'Criteria',
  vrd: 'Verdict',
  scr: 'Score',
}

function GroundingBadge({ status, factChecked }) {
  if (status === 'grounded') {
    return (
      <div style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.4rem',
        padding: '0.3rem 0.65rem',
        borderRadius: 'var(--radius-sm, 4px)',
        background: 'rgba(34, 197, 94, 0.12)',
        border: '1px solid rgba(34, 197, 94, 0.35)',
        color: '#22c55e',
        fontSize: '0.75rem',
        fontWeight: 600,
        marginBottom: '0.75rem',
      }}>
        <span>●</span> Verified Reference Grounded
      </div>
    )
  }
  if (status === 'unverified') {
    return (
      <div style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.4rem',
        padding: '0.3rem 0.65rem',
        borderRadius: 'var(--radius-sm, 4px)',
        background: 'rgba(245, 158, 11, 0.12)',
        border: '1px solid rgba(245, 158, 11, 0.35)',
        color: '#f59e0b',
        fontSize: '0.75rem',
        fontWeight: 600,
        marginBottom: '0.75rem',
      }}>
        <span>⚠️</span> Unverified Challenge (Audit failed)
      </div>
    )
  }
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.4rem',
      padding: '0.3rem 0.65rem',
      borderRadius: 'var(--radius-sm, 4px)',
      background: 'rgba(148, 163, 184, 0.12)',
      border: '1px solid rgba(148, 163, 184, 0.3)',
      color: 'var(--text-muted, #94a3b8)',
      fontSize: '0.75rem',
      fontWeight: 500,
      marginBottom: '0.75rem',
    }}>
      <span>ℹ️</span> General Knowledge Mode
    </div>
  )
}

function DebateStep({ type, label, children, animationDelay }) {
  return (
    <div
      className="debate-step fade-in"
      style={animationDelay != null ? { animationDelay: `${animationDelay}ms` } : undefined}
    >
      <div className={`step-badge ${type}`}>
        {label.slice(0, 3).toUpperCase()}
      </div>
      <div className="step-content">
        <div className="step-label">{label}</div>
        <div className="step-text">{children}</div>
      </div>
    </div>
  )
}

/**
 * CalibrationChip — colour-coded badge showing predicted vs actual delta.
 * Only rendered when the backend returns a non-null calibration_delta
 * (i.e. slider_touched was True).
 *
 * Colour bands:
 *   |delta| ≤ 0.15 → green  (well calibrated)
 *   |delta| ≤ 0.30 → amber  (moderate gap)
 *   |delta| > 0.30 → red    (significantly over/underconfident)
 */
function CalibrationChip({ predictedScore, actualScore, delta }) {
  const abs = Math.abs(delta)
  const color = abs <= 0.15 ? 'var(--color-success, #22c55e)'
    : abs <= 0.30 ? 'var(--color-warn, #f59e0b)'
    : 'var(--color-danger, #ef4444)'

  const predicted = Math.round(predictedScore * 100)
  const actual = Math.round(actualScore * 100)
  const sign = delta >= 0 ? '+' : ''
  const deltaDisplay = `${sign}${Math.round(delta * 100)}%`

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      marginTop: '1rem',
      padding: '0.5rem 0.85rem',
      borderRadius: 'var(--radius-md)',
      background: 'var(--bg-secondary)',
      border: `1px solid ${color}`,
      fontSize: '0.8rem',
      color: 'var(--text-secondary)',
    }}>
      <span style={{ fontWeight: 600, color }}>Calibration</span>
      <span>You predicted <strong>{predicted}%</strong></span>
      <span style={{ color: 'var(--text-muted)' }}>·</span>
      <span>Actual <strong>{actual}%</strong></span>
      <span style={{ color: 'var(--text-muted)' }}>·</span>
      <span style={{ fontWeight: 700, color }}>Δ {deltaDisplay}</span>
    </div>
  )
}

function ScoreDisplay({ scoring }) {
  const score = scoring.mastery_score
  const cls = score >= 0.75 ? 'high' : score >= 0.45 ? 'mid' : 'low'

  return (
    <div className="score-ring">
      <div className={`score-number ${cls}`}>
        {(score * 100).toFixed(0)}
        <span style={{ fontSize: '1rem', color: 'var(--text-muted)' }}>%</span>
      </div>
      <div className="score-meta">
        <div className={`verdict-badge ${scoring.verdict}`}>
          {scoring.verdict.replace('_', ' ')}
        </div>
        <div className="weak-point">
          Review: <strong>{scoring.weak_point}</strong>
        </div>
        {scoring.failure_mode && (
          <div className="weak-point" style={{ marginTop: '0.2rem' }}>
            Pattern: <strong>{scoring.failure_mode.replace(/_/g, ' ')}</strong>
          </div>
        )}
      </div>
    </div>
  )
}

export default function DebateSession({ token, topic, onBack }) {
  const { mode } = useTheme()
  // Core loop state
  const [phase, setPhase] = useState('explain')
  // explain | challenging | challenge_shown | rebutting | scored | compress
  const [explanation, setExplanation] = useState('')
  const [rebuttal, setRebuttal] = useState('')
  const [compression, setCompression] = useState('')
  const [roundId, setRoundId] = useState(null)
  const [generation, setGeneration] = useState(null)
  const [scoring, setScoring] = useState(null)
  const [nextReview, setNextReview] = useState(null)
  const [calibrationDelta, setCalibrationDelta] = useState(null)
  const [error, setError] = useState('')

  // Phase 4: Grounding & Flagging state
  const [groundingStatus, setGroundingStatus] = useState(null)
  const [factChecked, setFactChecked] = useState(false)
  const [showFlagInput, setShowFlagInput] = useState(false)
  const [flagReason, setFlagReason] = useState('')
  const [isFlagged, setIsFlagged] = useState(false)
  const [flagSubmitting, setFlagSubmitting] = useState(false)

  // Phase 2: confidence calibration state
  const [predictedScore, setPredictedScore] = useState(0.5)
  const [sliderTouched, setSliderTouched] = useState(false)

  async function handleExplain(e) {
    e.preventDefault()
    setError('')
    setPhase('challenging')
    try {
      const data = await debateStart(token, {
        topic_id: topic.id,
        student_explanation: explanation,
        predicted_score: predictedScore,
        slider_touched: sliderTouched,
        mode,
      })
      setRoundId(data.round_id)
      setGeneration(data.generation)
      setGroundingStatus(data.grounding_status)
      setFactChecked(data.fact_checked)
      setPhase('challenge_shown')
    } catch (err) {
      setError(err.message)
      setPhase('explain')
    }
  }

  async function handleFlagSubmit(e) {
    e.preventDefault()
    if (!roundId) return
    setFlagSubmitting(true)
    try {
      await flagDebateRound(token, roundId, { reason: flagReason || undefined })
      setIsFlagged(true)
      setShowFlagInput(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setFlagSubmitting(false)
    }
  }

  async function handleRebuttal(e) {
    e.preventDefault()
    setError('')
    setPhase('rebutting')
    try {
      const data = await debateRespond(token, {
        round_id: roundId,
        student_rebuttal: rebuttal,
        mode,
      })
      setScoring(data.scoring)
      setNextReview(data.next_review_due)
      // calibration_delta is null when slider was not touched — render nothing in that case
      setCalibrationDelta(data.calibration_delta ?? null)
      setPhase('scored')
    } catch (err) {
      setError(err.message)
      setPhase('challenge_shown')
    }
  }

  async function handleCompress(e) {
    e.preventDefault()
    setError('')
    try {
      await debateCompress(token, roundId, { summary: compression })
    } catch (err) {
      // Non-fatal: if compress fails, still allow the user to proceed
    }
    handleReset()
  }

  function handleCompressSkip() {
    handleReset()
  }

  function handleReset() {
    setPhase('explain')
    setExplanation('')
    setRebuttal('')
    setCompression('')
    setRoundId(null)
    setGeneration(null)
    setScoring(null)
    setNextReview(null)
    setCalibrationDelta(null)
    setError('')
    setPredictedScore(0.5)
    setSliderTouched(false)
    setGroundingStatus(null)
    setFactChecked(false)
    setShowFlagInput(false)
    setFlagReason('')
    setIsFlagged(false)
  }

  const challengeTypeLabel = generation?.challenge_type?.replace(/_/g, ' ')

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <button
          id="back-btn"
          className="btn btn-secondary btn-sm"
          onClick={onBack}
        >
          ← Topics
        </button>
        <div>
          <h1 style={{ fontSize: '1.2rem', marginBottom: 0 }}>{topic.name}</h1>
          {topic.course && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
              {topic.course}
            </div>
          )}
        </div>
      </div>

      {/* ── Step 1: Explain + Confidence Slider ── */}
      {(phase === 'explain' || phase === 'challenging') && (
        <div className="card">
          <div className="card-title">Your Explanation</div>
          <p style={{ marginBottom: '1rem' }}>
            Explain <strong style={{ color: 'var(--text-primary)' }}>{topic.name}</strong> in
            your own words. Be as complete as you can — the agent will challenge the weakest part.
          </p>
          <form onSubmit={handleExplain}>
            <div className="form-group">
              <textarea
                id="explanation-input"
                maxLength={1000}
                placeholder={getCopy(mode, 'explainPrompt')}
                value={explanation}
                onChange={e => setExplanation(e.target.value)}
                required
                minLength={10}
                maxLength={5000}
                style={{ minHeight: '160px' }}
              />
            </div>

            {/* Phase 2: Confidence slider (10.1) */}
            <div className="form-group" style={{ marginTop: '1.25rem' }}>
              <label
                htmlFor="confidence-slider"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}
              >
                <span>Before submitting — how confident are you? <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(optional)</span></span>
                <span style={{ fontWeight: 700, color: 'var(--text-primary)', minWidth: '3rem', textAlign: 'right' }}>
                  {Math.round(predictedScore * 100)}%
                </span>
              </label>
              <input
                id="confidence-slider"
                type="range"
                min={0}
                max={100}
                step={1}
                value={Math.round(predictedScore * 100)}
                onChange={e => {
                  setPredictedScore(Number(e.target.value) / 100)
                  setSliderTouched(true)  // first interaction marks it as a real prediction
                }}
                style={{ width: '100%', marginTop: '0.4rem', cursor: 'pointer' }}
              />
              {!sliderTouched && (
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                  Move the slider to record a prediction. Untouched defaults are excluded from calibration tracking.
                </div>
              )}
            </div>

            {error && <div className="error-msg">{error}</div>}
            <button
              id="submit-explanation-btn"
              className="btn btn-primary"
              type="submit"
              disabled={phase === 'challenging'}
            >
              {phase === 'challenging'
                ? <><span className="spinner" /> Generating challenge…</>
                : 'Submit & Get Challenged'
              }
            </button>
          </form>
        </div>
      )}

      {/* ── Skeleton while challenge is loading ── */}
      {phase === 'challenging' && (
        <div className="card">
          <div className="card-title">The Challenge</div>
          <div className="debate-step skeleton">
            <div className="step-badge skeleton-badge">...</div>
            <div className="step-content">
              <div className="step-label skeleton-label">Agent is thinking...</div>
              <div className="step-text skeleton-text"></div>
            </div>
          </div>
        </div>
      )}

      {/* ── Step 2: Four-step narration + Rebuttal ── */}
      {(phase === 'challenge_shown' || phase === 'rebutting' || phase === 'scored' || phase === 'compress') && generation && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <div className="card-title" style={{ marginBottom: 0 }}>The Challenge</div>
            {groundingStatus && (
              <GroundingBadge status={groundingStatus} factChecked={factChecked} />
            )}
          </div>

          {/* Your explanation recap */}
          <div style={{
            background: 'var(--bg-secondary)',
            borderRadius: 'var(--radius-md)',
            padding: '0.75rem 1rem',
            marginBottom: '1rem',
            fontSize: '0.85rem',
            color: 'var(--text-secondary)',
            borderLeft: '3px solid var(--border-focus)',
          }}>
            <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.3rem' }}>
              Your Explanation
            </div>
            {explanation}
          </div>

          {/* ACKNOWLEDGE → LOCATE → CLASSIFY → PRESENT */}
          <DebateStep type="ack" label={STEP_LABELS.ack}>
            {generation.acknowledgment}
          </DebateStep>
          <DebateStep type="loc" label={STEP_LABELS.loc}>
            {generation.focus_area}
          </DebateStep>
          <DebateStep type="cls" label={STEP_LABELS.cls}>
            <span className="challenge-type-pill">{challengeTypeLabel}</span>
            <br />
            A {challengeTypeLabel} challenge is coming.
          </DebateStep>
          <DebateStep type="chl" label={STEP_LABELS.chl}>
            {generation.challenge}
          </DebateStep>

          {/* Phase 4: Dispute Flagging (12.2) */}
          <div style={{ marginTop: '0.75rem', marginBottom: '0.5rem' }}>
            {!isFlagged ? (
              <div>
                {!showFlagInput ? (
                  <button
                    id="flag-counterargument-btn"
                    type="button"
                    onClick={() => setShowFlagInput(true)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      fontSize: '0.75rem',
                      padding: 0,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                    }}
                  >
                    <span>🚩</span> Flag challenge as factually incorrect
                  </button>
                ) : (
                  <form onSubmit={handleFlagSubmit} style={{ marginTop: '0.5rem', background: 'var(--bg-secondary)', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.4rem' }}>
                      Dispute Challenge Factuality
                    </div>
                    <input
                      id="flag-reason-input"
                      type="text"
                      maxLength={500}
                      placeholder="Why is this counterargument factually incorrect? (optional)"
                      value={flagReason}
                      onChange={e => setFlagReason(e.target.value)}
                      maxLength={500}
                      style={{ width: '100%', fontSize: '0.8rem', marginBottom: '0.5rem' }}
                    />
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        id="submit-flag-btn"
                        className="btn btn-secondary btn-sm"
                        type="submit"
                        disabled={flagSubmitting}
                      >
                        {flagSubmitting ? 'Flagging...' : 'Confirm Flag'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setShowFlagInput(false)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </div>
            ) : (
              <div style={{ fontSize: '0.75rem', color: 'var(--color-warn, #f59e0b)', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
                <span>✓</span> Challenge flagged for factual review
              </div>
            )}
          </div>

          <hr className="divider" />

          {/* Rebuttal form */}
          {(phase === 'challenge_shown' || phase === 'rebutting') && (
            <form onSubmit={handleRebuttal}>
              <div className="form-group">
                <label htmlFor="rebuttal-input">Your Response</label>
                <textarea
                  id="rebuttal-input"
                  maxLength={2000}
                  placeholder={getCopy(mode, 'rebuttalPrompt')}
                  value={rebuttal}
                  onChange={e => setRebuttal(e.target.value)}
                  required
                  minLength={5}
                  maxLength={5000}
                />
              </div>
              {error && <div className="error-msg">{error}</div>}
              <button
                id="submit-rebuttal-btn"
                className="btn btn-primary"
                type="submit"
                disabled={phase === 'rebutting'}
              >
                {phase === 'rebutting'
                  ? <><span className="spinner" /> Scoring…</>
                  : 'Submit Response'
                }
              </button>
            </form>
          )}
        </div>
      )}

      {/* ── Step 3: Five-step scoring result (staggered reveal) ── */}
      {(phase === 'scored' || phase === 'compress') && scoring && (
        <div className="card">
          <div className="card-title">Scoring</div>

          {/*
            Phase 2: staggered reveal — criteria → verdict → score.
            Each step uses animationDelay so the student sees criteria
            and verdict BEFORE the score number appears (Section 11 principle).
            ~200ms per step; adjust the CSS variable if it feels slow on repetition.
          */}
          <DebateStep type="cri" label={STEP_LABELS.cri} animationDelay={0}>
            {scoring.criteria}
          </DebateStep>
          <DebateStep type="vrd" label={STEP_LABELS.vrd} animationDelay={200}>
            {scoring.verdict_explanation
              ? scoring.verdict_explanation
              : scoring.verdict === 'held_up' ? 'Your response held up.'
              : scoring.verdict === 'partial'  ? 'Your response partially held up.'
              : 'Your response did not hold up.'}
          </DebateStep>
          <DebateStep type="scr" label={STEP_LABELS.scr} animationDelay={400}>
            <ScoreDisplay scoring={scoring} />
          </DebateStep>

          {/* Phase 2: calibration chip — only shown when slider was touched */}
          {calibrationDelta !== null && (
            <CalibrationChip
              predictedScore={predictedScore}
              actualScore={scoring.mastery_score}
              delta={calibrationDelta}
            />
          )}

          {nextReview && (
            <div className="next-review">
              Next review: <span>
                {new Date(nextReview).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'short', day: 'numeric',
                })}
              </span>
            </div>
          )}
        </div>
      )}

      {/* ── Step 4 (Phase 2): Compression summary (10.3) ── */}
      {phase === 'compress' && (
        <div className="card">
          <div className="card-title">One-Sentence Takeaway</div>
          <p style={{ marginBottom: '1rem', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
            In one sentence, what did you learn from this round?{' '}
            <span style={{ color: 'var(--text-muted)' }}>
              Writing this down strengthens retention (testing-effect, Section 10.3).
            </span>
          </p>
          <form onSubmit={handleCompress}>
            <div className="form-group">
              <textarea
                id="compression-input"
                maxLength={200}
                placeholder='e.g. "I learned that photosynthesis requires both light energy and CO₂ as separate inputs, not one."'
                value={compression}
                onChange={e => setCompression(e.target.value)}
                required
                minLength={5}
                style={{ minHeight: '80px' }}
              />
            </div>
            {error && <div className="error-msg">{error}</div>}
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
              <button
                id="submit-compression-btn"
                className="btn btn-primary"
                type="submit"
              >
                Save & Finish
              </button>
              <button
                id="skip-compression-btn"
                type="button"
                onClick={handleCompressSkip}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  textDecoration: 'underline',
                  padding: 0,
                }}
              >
                Skip
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── "Try Another Round" — only shown in scored phase before compression ── */}
      {phase === 'scored' && scoring && (
        <div style={{ marginTop: '1rem' }}>
          <hr className="divider" />
          <button
            id="try-again-btn"
            className="btn btn-secondary"
            onClick={() => setPhase('compress')}
            style={{ width: '100%' }}
          >
            Continue →
          </button>
        </div>
      )}
    </div>
  )
}
