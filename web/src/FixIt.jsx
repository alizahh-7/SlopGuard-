import { useState } from 'react'
import './FixIt.css'

const FIXABLE = ['auto', 'requirements', 'package_json', 'text']
const ACTION = { replace: 'Replaced with a suggestion', remove: 'Removed', manual: 'Fix by hand', suggest: 'Suggestion only' }

function fileName(kind) {
  if (kind === 'package_json') return 'package.fixed.json'
  if (kind === 'requirements') return 'requirements.fixed.txt'
  return 'dependencies.fixed.txt'
}

function DiffView({ diff }) {
  if (!diff) return <p className="fx-muted">No file changes to show.</p>
  return (
    <pre className="fx-diff" aria-label="Changes as a diff">
      {diff.split('\n').map((line, index) => {
        let cls = 'fx-ctx'
        if (line.startsWith('+++') || line.startsWith('---')) cls = 'fx-meta'
        else if (line.startsWith('@@')) cls = 'fx-hunk'
        else if (line.startsWith('+')) cls = 'fx-add'
        else if (line.startsWith('-')) cls = 'fx-del'
        return <span key={index} className={cls}>{line || ' '}</span>
      })}
    </pre>
  )
}

export default function FixIt({ content, kind, result, url }) {
  const [state, setState] = useState({ status: 'idle' })
  const [copied, setCopied] = useState(false)
  const worst = result && result.summary && result.summary.worst_verdict
  if (worst !== 'RISKY' && worst !== 'BLOCK') return null
  if (!FIXABLE.includes(kind)) return null

  async function run() {
    setState({ status: 'loading' })
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, kind }),
      })
      const body = await response.json().catch(() => null)
      if (!response.ok || !body || typeof body.fixed_content !== 'string') {
        throw new Error('The fix service returned an unexpected response.')
      }
      setState({ status: 'done', data: body })
    } catch (error) {
      setState({ status: 'error', message: error.message || 'Could not build a fixed version.' })
    }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard may be unavailable */ }
  }

  function download(text) {
    const blob = new Blob([text], { type: 'text/plain' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = fileName(kind)
    link.click()
    URL.revokeObjectURL(link.href)
  }

  const data = state.data
  return (
    <section className="fx" aria-labelledby="fx-title">
      <div className="fx-head">
        <div>
          <h2 id="fx-title">Fix it for me</h2>
          <p className="fx-muted">Build a safer version of your input. You stay in control: nothing is installed.</p>
        </div>
        <button type="button" className="fx-primary" onClick={run} disabled={state.status === 'loading'}>
          {state.status === 'loading' ? 'Building fix...' : 'Fix it for me'}
        </button>
      </div>

      {state.status === 'error' && <p className="fx-error" role="alert">{state.message}</p>}

      {data && (
        <div className="fx-body" aria-live="polite">
          <p>
            <b>{data.changed_count} changed</b>, {data.needs_review_count} need your review.
            {!data.supported && ' This input type cannot be rewritten automatically, so these are suggestions only.'}
          </p>
          <ul className="fx-changes">
            {data.changes.map((change) => (
              <li key={change.ecosystem + ':' + change.package}>
                <b>{change.package}</b> <span className="fx-tag">{ACTION[change.action] || change.action}</span>
                {change.replacement && <> to <code>{change.replacement}</code></>}
                {change.needs_review && <span className="fx-review">needs review</span>}
                <p className="fx-muted">{change.reason}</p>
              </li>
            ))}
          </ul>
          <DiffView diff={data.diff} />
          {data.supported && data.fixed_content && (
            <div className="fx-actions">
              <button type="button" onClick={() => copy(data.fixed_content)}>{copied ? 'Copied' : 'Copy fixed file'}</button>
              <button type="button" onClick={() => download(data.fixed_content)}>Download fixed file</button>
            </div>
          )}
          <p className="fx-warn">Replacements are suggestions. Verify a package yourself before installing it.</p>
        </div>
      )}
    </section>
  )
}
