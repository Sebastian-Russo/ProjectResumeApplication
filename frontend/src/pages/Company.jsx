import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ExternalLink, ChevronDown, ChevronRight, Plus, X, Save } from 'lucide-react'
import { getPartner, updatePartner, addContact, removeContact, sendReply } from '../api'
import { useToast } from '../components/Toast'
import { ClassBadge, StatusBadge, ResponseTypeBadge } from '../components/Badge'
import Spinner from '../components/Spinner'

const STATUSES = [
  'sent','meeting_requested','meeting_scheduled','meeting_completed',
  'apply_link_received','applied_via_link','needs_reply','reply_sent',
  'keep_warm','offer_received','archived:rejected','archived:bad_email','archived:no_response'
]

const NEXT_ACTIONS = [
  '','schedule_meeting','submit_application','send_reply',
  'follow_up_in_30_days','follow_up_next_search','none'
]

export default function Company() {
  const { index } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const idx = parseInt(index)

  const [partner, setPartner] = useState(null)
  const [loading, setLoading] = useState(true)
  const [threadOpen, setThreadOpen] = useState(false)
  const [replyOpen, setReplyOpen] = useState(false)
  const [addContactOpen, setAddContactOpen] = useState(false)
  const [replying, setReplying] = useState(false)

  // Form state
  const [meetingNotes, setMeetingNotes] = useState('')
  const [notes, setNotes] = useState('')
  const [replyBody, setReplyBody] = useState('')
  const [emailContent, setEmailContent] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [newContact, setNewContact] = useState({ name: '', title: '', email: '', notes: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const p = await getPartner(idx)
      setPartner(p)
      setMeetingNotes(p.meeting_notes || '')
      setNotes(p.notes || '')
      setEmailContent(p.email_content || '')
    } catch (e) {
      toast('Failed to load company', 'error')
    }
    setLoading(false)
  }, [idx])

  useEffect(() => { load() }, [load])

  const patch = async (data, msg) => {
    try {
      const updated = await updatePartner(idx, data)
      setPartner(updated)
      if (msg) toast(msg)
    } catch (e) {
      toast(e.message || 'Update failed', 'error')
    }
  }

  const handleSendReply = async () => {
    if (!replyBody.trim()) { toast('Reply is empty', 'error'); return }
    setReplying(true)
    try {
      await sendReply(idx, replyBody)
      toast('Reply sent!')
      setReplyOpen(false)
      setReplyBody('')
      await load()
    } catch (e) {
      toast(e.message || 'Send failed', 'error')
    }
    setReplying(false)
  }

  const handleAddContact = async () => {
    if (!newContact.name) { toast('Name required', 'error'); return }
    try {
      const contacts = await addContact(idx, newContact)
      setPartner(p => ({ ...p, contacts }))
      setNewContact({ name: '', title: '', email: '', notes: '' })
      setAddContactOpen(false)
      toast('Contact added')
    } catch (e) {
      toast('Failed to add contact', 'error')
    }
  }

  const handleRemoveContact = async (ci) => {
    if (!confirm('Remove this contact?')) return
    try {
      const contacts = await removeContact(idx, ci)
      setPartner(p => ({ ...p, contacts }))
      toast('Contact removed')
    } catch (e) {
      toast('Failed', 'error')
    }
  }

  const handleAddTag = async () => {
    const t = tagInput.trim().toLowerCase()
    if (!t) return
    const tags = [...(partner.tags || []), t]
    await patch({ tags }, 'Tag added')
    setTagInput('')
  }

  const handleRemoveTag = async (t) => {
    const tags = (partner.tags || []).filter(x => x !== t)
    await patch({ tags }, 'Tag removed')
  }

  if (loading) return (
    <div className="flex items-center justify-center h-screen">
      <Spinner size={36} />
    </div>
  )

  if (!partner) return (
    <div className="flex items-center justify-center h-screen text-[var(--text-muted)]">
      Company not found.
    </div>
  )

  const isPositive = partner.status && ['meeting_requested','apply_link_received','needs_reply'].includes(partner.status)

  return (
    <div className="min-h-dvh flex flex-col">

      {/* Header */}
      <header className="sticky top-0 z-20 bg-[var(--bg-surface)] border-b border-[var(--border)] px-5 py-3 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--text-muted)] hover:text-purple-400 transition-colors">
          <ArrowLeft size={16} />
        </button>
        <h1 className="text-sm font-semibold flex-1 truncate">{partner.name}</h1>
        {partner.response_rate_days && (
          <span className="text-[11px] text-[var(--text-dim)]">{partner.response_rate_days}d to reply</span>
        )}
        <ClassBadge classification={partner.classification} />
      </header>

      {/* Email — full width, primary focus */}
      <section className="flex flex-col border-b border-[var(--border)]">
        <div className="bg-[var(--bg-surface)] border-b border-[var(--border)] px-4 py-2.5 flex items-center gap-2">
          <span className="text-xs text-[var(--text-muted)] flex-1">Outbound email draft</span>
          <button onClick={() => {
            const parts = emailContent.split('------------------------------------------------------------')
            const body = parts.length > 1 ? parts[parts.length - 1].trim() : emailContent
            navigator.clipboard.writeText(body).then(() => toast('Copied!'))
          }} className="btn-ghost text-[11px]">Copy</button>
          <button onClick={() => patch({ email_content: emailContent }, 'Saved')} className="btn-save text-[11px]">Save</button>
          {isPositive && (
            <button onClick={() => setReplyOpen(!replyOpen)} className="btn-teal text-[11px]">
              Draft Reply ↓
            </button>
          )}
        </div>

        {emailContent && (
          <div className="bg-[#13151f] border-b border-[var(--border)] px-4 py-2">
            {emailContent.split('\n').slice(0, 5).map((line, i) => {
              if (line.startsWith('TO:')) return (
                <div key={i} className="flex gap-2 text-xs mb-1">
                  <span className="text-[var(--text-dim)] w-12">To:</span>
                  <span className="text-purple-400">{line.slice(3).trim()}</span>
                </div>
              )
              if (line.startsWith('SUBJECT:')) return (
                <div key={i} className="flex gap-2 text-xs mb-1">
                  <span className="text-[var(--text-dim)] w-12">Subject:</span>
                  <span className="text-[var(--text-secondary)]">{line.slice(8).trim()}</span>
                </div>
              )
              return null
            })}
          </div>
        )}

        {emailContent ? (
          <textarea
            value={emailContent}
            onChange={e => setEmailContent(e.target.value)}
            className="email-editor w-full min-h-[65dvh] bg-[var(--bg-base)] text-[var(--text-primary)] border-none outline-none resize-y p-4 text-sm leading-relaxed font-sans box-border"
          />
        ) : (
          <div className="flex items-center justify-center min-h-[40dvh] text-[var(--text-muted)] text-sm">
            No drafted email on file.
          </div>
        )}

        {replyOpen && (
          <div className="border-t border-[var(--border)] bg-[#13151f] p-4">
            <div className="text-xs text-[var(--text-muted)] mb-2">Reply to {partner.name}</div>
            <textarea
              value={replyBody}
              onChange={e => setReplyBody(e.target.value)}
              rows={8}
              placeholder="Write your reply..."
              className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded p-3 text-sm text-[var(--text-primary)] outline-none focus:border-purple-500/50 resize-y font-sans leading-relaxed"
            />
            <div className="flex gap-2 justify-end mt-2">
              <button onClick={() => setReplyOpen(false)} className="btn-ghost text-xs">Cancel</button>
              <button onClick={handleSendReply} disabled={replying} className="btn-send text-xs flex items-center gap-1.5">
                {replying ? <Spinner size={10} /> : null}
                Send Reply
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Company details — scroll down */}
      <section className="bg-[#13151f] pb-8">
        <div className="px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-surface)]">
          <h2 className="text-[10px] text-[var(--text-dim)] uppercase tracking-widest">Company details</h2>
          <p className="text-[11px] text-[var(--text-muted)] mt-1">Status, notes, contacts — scroll down past the email</p>
        </div>

        <div className="grid md:grid-cols-2 xl:grid-cols-3">
          <Section title="Company">
            <InfoRow label="Website">
              {partner.website
                ? <a href={partner.website} target="_blank" className="text-purple-400 hover:underline flex items-center gap-1">
                    {partner.website} <ExternalLink size={10} />
                  </a>
                : '—'}
            </InfoRow>
            <InfoRow label="Email">{partner.contact_email || '—'}</InfoRow>
            <InfoRow label="Careers">
              {partner.career_page_url
                ? <a href={partner.career_page_url} target="_blank" className="text-purple-400 hover:underline flex items-center gap-1">
                    View <ExternalLink size={10} />
                  </a>
                : 'Not found'}
            </InfoRow>
            {partner.sent_at && <InfoRow label="Sent">{partner.sent_at.slice(0, 10)}</InfoRow>}
          </Section>

          {/* Response */}
          {partner.response_type && (
            <Section title="Response">
              <InfoRow label="Type"><ResponseTypeBadge type={partner.response_type} /></InfoRow>
              {partner.last_reply && (
                <InfoRow label="Received">{partner.last_reply.slice(0,16).replace('T',' ')}</InfoRow>
              )}
              {partner.email_thread && (
                <InfoRow label="Summary">
                  <span className="text-[11px] leading-relaxed">{partner.email_thread}</span>
                </InfoRow>
              )}
              {partner.apply_url && (
                <div className="mt-2 bg-teal-500/8 border border-teal-500/20 rounded p-2.5">
                  <div className="text-[10px] text-teal-400 uppercase tracking-wide mb-1.5">🔗 Application Link</div>
                  <a href={partner.apply_url} target="_blank"
                    className="text-teal-400 text-xs hover:underline break-all flex items-center gap-1">
                    {partner.apply_url} <ExternalLink size={10} className="shrink-0" />
                  </a>
                </div>
              )}
              {/* Full reply thread */}
              {partner.reply_body && (
                <div className="mt-2">
                  <button onClick={() => setThreadOpen(!threadOpen)}
                    className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] hover:text-purple-400 transition-colors w-full border border-[var(--border)] rounded px-2 py-1.5">
                    {threadOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    View full reply
                  </button>
                  {threadOpen && (
                    <div className="mt-1.5 bg-[var(--bg-surface)] border border-[var(--border)] rounded p-3 text-[11px] text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {partner.reply_body}
                    </div>
                  )}
                </div>
              )}
            </Section>
          )}

          {/* Meeting notes */}
          <Section title="Meeting Notes">
            <textarea
              value={meetingNotes}
              onChange={e => setMeetingNotes(e.target.value)}
              rows={3}
              placeholder="Notes about calls, interviews..."
              className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded p-2 text-xs text-[var(--text-primary)] outline-none focus:border-purple-500/50 resize-none font-sans leading-relaxed"
            />
            <div className="flex gap-1.5 mt-1.5 flex-wrap">
              {[['scheduled','📅','blue'],['completed','✅','green'],['offer','🎯','purple'],['pass','❌','red']].map(([o,e,c]) => (
                <button key={o} onClick={() => patch({ meeting_notes: meetingNotes, meeting_outcome: o }, `Meeting → ${o}`)}
                  className={`text-[11px] px-2 py-1 rounded border transition-colors
                    border-${c}-500/40 text-${c}-400 hover:bg-${c}-500/10`}>
                  {e} {o}
                </button>
              ))}
            </div>
            <div className="flex justify-end mt-1.5">
              <button onClick={() => patch({ meeting_notes: meetingNotes }, 'Notes saved')} className="btn-save text-[11px]">
                <Save size={10} className="inline mr-1" />Save
              </button>
            </div>
          </Section>

          {/* Scratchpad */}
          <Section title="Notes">
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
              placeholder="General notes, context, thoughts..."
              className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded p-2 text-xs text-[var(--text-primary)] outline-none focus:border-purple-500/50 resize-none font-sans leading-relaxed"
            />
            <div className="flex justify-end mt-1.5">
              <button onClick={() => patch({ notes }, 'Notes saved')} className="btn-save text-[11px]">
                <Save size={10} className="inline mr-1" />Save
              </button>
            </div>
          </Section>

          {/* Status */}
          <Section title="Status">
            <div className="flex flex-col gap-1">
              {STATUSES.map(s => (
                <button key={s} onClick={() => patch({ status: s }, `Status → ${s.replace(/[_:]/g,' ')}`)}
                  className={`text-left text-[11px] px-2 py-1.5 rounded border transition-colors
                    ${partner.status === s
                      ? 'border-purple-500/50 text-purple-400 bg-purple-500/8'
                      : 'border-[var(--border)] text-[var(--text-secondary)] hover:border-purple-500/30 hover:text-purple-400'}`}>
                  {s.replace(/_/g,' ').replace(':',' — ')}
                </button>
              ))}
            </div>
          </Section>

          {/* Next action */}
          <Section title="Next Action">
            <select
              value={partner.next_action || ''}
              onChange={e => patch({ next_action: e.target.value }, 'Next action saved')}
              className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1.5 text-xs text-[var(--text-secondary)] outline-none focus:border-purple-500/50 mb-2">
              {NEXT_ACTIONS.map(na => (
                <option key={na} value={na}>{na ? na.replace(/_/g,' ') : '— select —'}</option>
              ))}
            </select>
            <input
              type="date"
              value={partner.next_action_date || ''}
              onChange={e => patch({ next_action_date: e.target.value }, 'Date saved')}
              className="w-full bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1.5 text-xs text-[var(--text-secondary)] outline-none focus:border-purple-500/50"
            />
          </Section>

          {/* Tags */}
          <Section title="Tags">
            <div className="flex flex-wrap gap-1.5 mb-2">
              {(partner.tags || []).map(t => (
                <span key={t} className="flex items-center gap-1 text-[11px] bg-[var(--bg-raised)] text-[var(--text-secondary)] rounded px-2 py-0.5">
                  {t}
                  <button onClick={() => handleRemoveTag(t)} className="text-[var(--text-dim)] hover:text-red-400 transition-colors">
                    <X size={9} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-1.5">
              <input
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddTag()}
                placeholder="Add tag..."
                className="flex-1 bg-[var(--bg-surface)] border border-[var(--border)] rounded px-2 py-1 text-xs outline-none focus:border-purple-500/50"
              />
              <button onClick={handleAddTag} className="btn-ghost text-[11px] px-2">Add</button>
            </div>
          </Section>

          {/* Contacts */}
          <Section title="Contacts">
            {(partner.contacts || []).length === 0 && (
              <div className="text-[11px] text-[var(--text-dim)] mb-2">No contacts yet.</div>
            )}
            {(partner.contacts || []).map((c, ci) => (
              <div key={ci} className="bg-[var(--bg-surface)] border border-[var(--border)] rounded p-2.5 mb-2 flex justify-between items-start">
                <div>
                  <div className="text-xs font-medium">{c.name}</div>
                  <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
                    {c.title}{c.title && c.email ? ' · ' : ''}{c.email}
                  </div>
                  {c.notes && <div className="text-[11px] text-[var(--text-dim)] mt-0.5 italic">{c.notes}</div>}
                  <div className="text-[10px] text-[var(--text-dim)] mt-0.5">Added {c.date_added}</div>
                </div>
                <button onClick={() => handleRemoveContact(ci)} className="text-[var(--text-dim)] hover:text-red-400 transition-colors ml-2 mt-0.5">
                  <X size={12} />
                </button>
              </div>
            ))}
            <button onClick={() => setAddContactOpen(!addContactOpen)}
              className="flex items-center gap-1 text-[11px] text-[var(--text-muted)] hover:text-purple-400 transition-colors border border-[var(--border)] rounded px-2 py-1.5 w-full">
              <Plus size={11} /> Add Contact
            </button>
            {addContactOpen && (
              <div className="mt-2 bg-[var(--bg-surface)] border border-[var(--border)] rounded p-3 flex flex-col gap-2">
                <div className="grid grid-cols-2 gap-2">
                  <input value={newContact.name}  onChange={e => setNewContact(c => ({...c, name: e.target.value}))}  placeholder="Name"  className="contact-input" />
                  <input value={newContact.title} onChange={e => setNewContact(c => ({...c, title: e.target.value}))} placeholder="Title" className="contact-input" />
                </div>
                <input value={newContact.email} onChange={e => setNewContact(c => ({...c, email: e.target.value}))} placeholder="Email" className="contact-input" />
                <input value={newContact.notes} onChange={e => setNewContact(c => ({...c, notes: e.target.value}))} placeholder="Notes" className="contact-input" />
                <div className="flex justify-end">
                  <button onClick={handleAddContact} className="btn-save text-[11px]">Save Contact</button>
                </div>
              </div>
            )}
          </Section>

          {/* Status history */}
          {partner.status_history && (
            <Section title="History">
              {partner.status_history.split('|').filter(Boolean).map((entry, i) => (
                <div key={i} className="text-[10px] text-[var(--text-dim)] py-1.5 border-b border-[var(--border)]/40 leading-relaxed">
                  {entry.replace(/:/g, ' — ')}
                </div>
              ))}
            </Section>
          )}
        </div>
      </section>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="px-4 py-3 border-b border-[var(--border)]">
      <h3 className="text-[10px] text-[var(--text-dim)] uppercase tracking-widest mb-2.5">{title}</h3>
      {children}
    </div>
  )
}

function InfoRow({ label, children }) {
  return (
    <div className="mb-2">
      <div className="text-[10px] text-[var(--text-dim)] uppercase tracking-wide mb-0.5">{label}</div>
      <div className="text-xs text-[var(--text-secondary)]">{children}</div>
    </div>
  )
}
