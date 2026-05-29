import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { RefreshCw, Send, RotateCcw, ThumbsUp, Flame, Archive, Download, Camera } from 'lucide-react'
import { getPartners, getStats, getActivity, scanInbox, sendBatch, retryBatch,
         sendThankyou, sendKeepwarm, archiveNoResponse, takeSnapshot, exportCsv } from '../api'
import { useToast } from '../components/Toast'
import StatCard from '../components/StatCard'
import { ClassBadge, StatusBadge } from '../components/Badge'
import Spinner from '../components/Spinner'

const FILTERS = [
  { key: 'action',    label: 'Action Queue' },
  { key: 'meeting',   label: 'Meetings' },
  { key: 'apply',     label: 'Apply Links',  color: 'teal' },
  { key: 'keep_warm', label: 'Keep Warm',    color: 'orange' },
  { key: 'sent',      label: 'Sent' },
  { key: 'bounced',   label: 'Bounced',      color: 'orange' },
  { key: 'rejected',  label: 'Rejected',     color: 'red' },
  { key: 'due_today', label: 'Due Today',    color: 'yellow' },
  { key: 'pending',   label: 'Pending' },
  { key: 'ignored',   label: 'Blocked' },
  { key: 'archived',  label: 'Archived' },
  { key: 'all',       label: 'All' },
]

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()

  const filter = searchParams.get('filter') || 'action'
  const search = searchParams.get('search') || ''
  const tag = searchParams.get('tag') || ''

  const [partners, setPartners] = useState([])
  const [stats, setStats] = useState({})
  const [activity, setActivity] = useState([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [statsOpen, setStatsOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, s, a] = await Promise.all([
        getPartners(filter, search, tag),
        getStats(),
        getActivity()
      ])
      setPartners(p)
      setStats(s)
      setActivity(a)
    } catch (e) {
      toast('Failed to load data', 'error')
    }
    setLoading(false)
  }, [filter, search, tag])

  useEffect(() => { load() }, [load])

  const setFilter = (f) => setSearchParams({ filter: f, search, tag })
  const setSearch = (s) => setSearchParams({ filter, search: s, tag })

  const action = async (label, fn, successMsg) => {
    setActionLoading(label)
    try {
      const r = await fn()
      toast(successMsg(r))
      await load()
    } catch (e) {
      toast(e.message || 'Action failed', 'error')
    }
    setActionLoading('')
  }

  const handleScan = () => action('scan', scanInbox,
    r => `Scan done — meetings: ${r.stats?.positive_meeting||0}, apply: ${r.stats?.positive_apply||0}, bounces: ${r.stats?.bounce||0}`)

  const handleSendBatch = () => action('send', sendBatch,
    r => `Sent: ${r.sent} | Failed: ${r.failed} | Remaining: ${r.remaining}${r.rate_limited ? ' ⚠️ rate limited' : ''}`)

  const handleRetry = () => action('retry', retryBatch,
    r => `Retry — Sent: ${r.sent} | Remaining: ${r.remaining}`)

  const handleThankyou = () => action('thankyou', sendThankyou,
    r => `Thank you sent: ${r.sent} | Remaining: ${r.remaining}`)

  const handleKeepwarm = () => action('keepwarm', sendKeepwarm,
    r => `Keep warm sent: ${r.sent} | Remaining: ${r.remaining}`)

  const handleArchive = async () => {
    if (!confirm('Archive all companies with no response after 30 days?')) return
    action('archive', () => archiveNoResponse(30),
      r => `Archived: ${r.archived} companies`)
  }

  const isLoading = (key) => actionLoading === key

  return (
    <div className="min-h-dvh flex flex-col">

      {/* Header */}
      <header className="sticky top-0 z-20 bg-[var(--bg-surface)] border-b border-[var(--border)] px-6 py-3 flex items-center gap-3 flex-wrap">
        <h1 className="text-purple-400 font-semibold text-sm mr-2">🚀 Resume Tracker</h1>

        <button onClick={handleScan} disabled={isLoading('scan')}
          className="btn-purple flex items-center gap-1.5">
          {isLoading('scan') ? <Spinner size={12} /> : <RefreshCw size={12} />}
          Scan Inbox
        </button>

        <div className="w-px h-5 bg-[var(--border)]" />

        <button onClick={handleSendBatch} disabled={isLoading('send')}
          className="btn-green flex items-center gap-1.5">
          {isLoading('send') ? <Spinner size={12} /> : <Send size={12} />}
          Send Pending ({stats.pending ?? 0})
        </button>

        <button onClick={handleRetry} disabled={isLoading('retry')}
          className="btn-orange flex items-center gap-1.5">
          {isLoading('retry') ? <Spinner size={12} /> : <RotateCcw size={12} />}
          Retry Bounced ({stats.retry_queued ?? 0})
        </button>

        <button onClick={handleThankyou} disabled={isLoading('thankyou')}
          className="btn-ghost flex items-center gap-1.5">
          {isLoading('thankyou') ? <Spinner size={12} /> : <ThumbsUp size={12} />}
          Thank You ({stats.thankyou_due ?? 0})
        </button>

        <button onClick={handleKeepwarm} disabled={isLoading('keepwarm')}
          className="btn-ghost flex items-center gap-1.5">
          {isLoading('keepwarm') ? <Spinner size={12} /> : <Flame size={12} />}
          Keep Warm ({stats.keepwarm_due ?? 0})
        </button>

        <div className="w-px h-5 bg-[var(--border)]" />

        <button onClick={handleArchive} className="btn-ghost flex items-center gap-1.5">
          <Archive size={12} /> Archive 30d
        </button>
        <button onClick={() => action('snapshot', takeSnapshot, () => 'Snapshot saved')}
          className="btn-ghost flex items-center gap-1.5">
          <Camera size={12} /> Snapshot
        </button>
        <button onClick={exportCsv} className="btn-ghost flex items-center gap-1.5">
          <Download size={12} /> Export
        </button>
      </header>

      {/* Stats — collapsed by default to leave room for the company list */}
      <div className="bg-[#13151f] border-b border-[var(--border)] px-6 py-2">
        <button
          type="button"
          onClick={() => setStatsOpen(o => !o)}
          className="text-[11px] text-[var(--text-muted)] hover:text-purple-400 transition-colors mb-2"
        >
          {statsOpen ? '▾ Hide stats' : '▸ Show stats & metrics'}
        </button>
        {statsOpen && (
          <>
            <div className="flex gap-2 flex-wrap mb-3 pb-2">
              <StatCard label="Total"    value={stats.total}              color="purple" active={filter==='all'}       onClick={() => setFilter('all')} />
              <StatCard label="Sent"     value={stats.sent}               color="blue"   active={filter==='sent'}      onClick={() => setFilter('sent')} />
              <StatCard label="Pending"  value={stats.pending}            color="gray"   active={filter==='pending'}   onClick={() => setFilter('pending')} />
              <StatCard label="Meetings" value={stats.meeting_requested}  color="green"  active={filter==='meeting'}   onClick={() => setFilter('meeting')} />
              <StatCard label="Apply"    value={stats.apply_link_received}color="teal"   active={filter==='apply'}     onClick={() => setFilter('apply')} />
              <StatCard label="Reply"    value={stats.needs_reply}        color="yellow" active={filter==='action'}    onClick={() => setFilter('action')} />
              <StatCard label="Warm"     value={stats.keep_warm}          color="orange" active={filter==='keep_warm'} onClick={() => setFilter('keep_warm')} />
              <StatCard label="Offers"   value={stats.offer_received}     color="pink" />
              <StatCard label="Rejected" value={stats.rejected}           color="red"    active={filter==='rejected'}  onClick={() => setFilter('rejected')} />
              <StatCard label="Bounced"  value={stats.bounced}            color="orange" active={filter==='bounced'}   onClick={() => setFilter('bounced')} />
              <StatCard label="Blocked"  value={stats.ignored}            color="gray"   active={filter==='ignored'}   onClick={() => setFilter('ignored')} />
              {(stats.due_today?.length > 0) &&
                <StatCard label="Due Today" value={stats.due_today?.length} color="yellow" active={filter==='due_today'} onClick={() => setFilter('due_today')} />}
            </div>
            <div className="flex gap-6 flex-wrap text-[11px] text-[var(--text-muted)] border-t border-[var(--border)] pt-2 pb-2">
              <div className="flex items-center gap-2">
                <span className="text-purple-400 font-semibold text-sm">{stats.response_rate ?? 0}%</span>
                response rate
              </div>
              <div className="flex items-center gap-2">
                <span className="text-blue-400 font-semibold text-sm">{stats.avg_days_to_response ?? 0}d</span>
                avg to reply
              </div>
              {Object.entries(stats.next_actions || {}).map(([k, v]) => (
                <div key={k} className="flex items-center gap-1.5">
                  <span className="bg-[var(--bg-raised)] text-purple-400 text-[10px] font-semibold px-1.5 py-0.5 rounded">{v}</span>
                  {k.replace(/_/g, ' ')}
                </div>
              ))}
              <div className="flex items-center gap-1.5">
                <span className="bg-[var(--bg-raised)] text-orange-400 text-[10px] font-semibold px-1.5 py-0.5 rounded">{stats.retry_queued ?? 0}</span>
                retry queued
              </div>
              <div className="flex items-center gap-1.5">
                <span className="bg-[var(--bg-raised)] text-red-400 text-[10px] font-semibold px-1.5 py-0.5 rounded">{stats.bad_email ?? 0}</span>
                exhausted
              </div>
            </div>
          </>
        )}
      </div>

      {/* Due today bar */}
      {stats.due_today?.length > 0 && (
        <div className="bg-yellow-500/5 border-b border-yellow-500/20 px-6 py-2 flex items-center gap-2 flex-wrap">
          <span className="text-yellow-400 text-[10px] font-semibold uppercase tracking-wide">⏰ Due Today</span>
          {stats.due_today.slice(0, 8).map(name => (
            <span key={name} className="text-[11px] bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 rounded px-2 py-0.5">{name}</span>
          ))}
          {stats.due_today.length > 8 && <span className="text-yellow-400 text-[11px]">+{stats.due_today.length - 8} more</span>}
        </div>
      )}

      {/* Filter bar */}
      <div className="border-b border-[var(--border)] px-6 py-2 flex gap-1.5 flex-wrap items-center">
        {FILTERS.map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`filter-pill ${filter === f.key ? 'active' : ''} ${f.color ? `color-${f.color}` : ''}`}>
            {f.label}
          </button>
        ))}
        {(stats.all_tags || []).map(t => (
          <button key={t} onClick={() => setSearchParams({ filter, search, tag: tag === t ? '' : t })}
            className={`filter-pill ${tag === t ? 'active' : ''}`}>
            {t}
          </button>
        ))}
        <span className="text-[11px] text-[var(--text-dim)] ml-1">{partners.length} shown</span>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search..."
          className="ml-auto bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1 text-xs outline-none focus:border-purple-500/60 w-40"
        />
      </div>

      {/* Main content */}
      <div className="flex flex-1 items-start">

        {/* Company list */}
        <main className="flex-1 px-6 py-3 space-y-1.5 pb-8">
          {loading ? (
            <div className="flex justify-center pt-16"><Spinner size={32} /></div>
          ) : partners.length === 0 ? (
            <div className="text-center pt-16 text-[var(--text-muted)]">No companies match this filter.</div>
          ) : partners.map(p => (
            <CompanyRow key={p.index} partner={p} onClick={() => navigate(`/company/${p.index}`)} />
          ))}
        </main>

        {/* Activity feed */}
        <aside className="hidden lg:block w-64 shrink-0 sticky top-0 self-start max-h-dvh overflow-y-auto border-l border-[var(--border)] bg-[#13151f]">
          <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
            <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-widest">Activity</span>
            <button onClick={load} className="text-[var(--text-dim)] hover:text-purple-400 transition-colors">
              <RefreshCw size={11} />
            </button>
          </div>
          {activity.length === 0 ? (
            <div className="px-4 py-4 text-[11px] text-[var(--text-dim)]">No activity yet.</div>
          ) : activity.map((a, i) => (
            <div key={i} className="px-4 py-2.5 border-b border-[var(--border)]/50">
              <div className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{a.msg}</div>
              <div className="text-[10px] text-[var(--text-dim)] mt-0.5">{a.ts?.slice(0, 16).replace('T', ' ')}</div>
            </div>
          ))}
        </aside>

      </div>

      {/* Scan overlay */}
      {scanning && (
        <div className="fixed inset-0 bg-black/75 flex flex-col items-center justify-center gap-4 z-50">
          <Spinner size={40} />
          <p className="text-sm">Scanning inbox...</p>
        </div>
      )}

    </div>
  )
}

function CompanyRow({ partner: p, onClick }) {
  const hl = {
    meeting_requested:   'border-l-2 border-l-emerald-500/60',
    apply_link_received: 'border-l-2 border-l-teal-500/60',
    needs_reply:         'border-l-2 border-l-yellow-500/60',
    keep_warm:           'border-l-2 border-l-orange-500/60',
  }[p.status] || ''

  return (
    <button onClick={onClick}
      className={`w-full text-left bg-[var(--bg-surface)] border border-[var(--border)] rounded-md px-3 py-3
        hover:border-purple-500/40 transition-colors ${hl}`}>
      <div className="flex items-center gap-2.5">
      <ClassBadge classification={p.classification} />
      <span className="flex-1 text-sm font-medium truncate">{p.name}</span>
      {p.apply_url && <span className="text-[10px] text-teal-400 bg-teal-500/10 border border-teal-500/20 rounded px-1.5 py-0.5">🔗 apply</span>}
      {p.next_action && p.next_action !== 'none' && (
        <span className="text-[10px] text-purple-400 bg-purple-500/8 border border-purple-500/15 rounded px-1.5 py-0.5">
          {p.next_action.replace(/_/g, ' ')}
        </span>
      )}
      {p.tags?.map(t => (
        <span key={t} className="text-[10px] text-slate-400 bg-[var(--bg-raised)] rounded px-1.5 py-0.5">{t}</span>
      ))}
      <StatusBadge status={p.status} />
      </div>
      {p.contact_email && (
        <div className="text-[11px] text-[var(--text-dim)] mt-1.5 pl-0.5 truncate">{p.contact_email}</div>
      )}
      <p className="text-[10px] text-[var(--text-muted)] mt-2">Click to open full email draft →</p>
    </button>
  )
}