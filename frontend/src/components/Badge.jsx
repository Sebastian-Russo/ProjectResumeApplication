export function ClassBadge({ classification }) {
    const styles = {
      has_careers: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
      no_careers:  'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20',
      ignore:      'bg-slate-500/10 text-slate-500 border border-slate-500/20',
    }
    return (
      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${styles[classification] || styles.ignore}`}>
        {classification?.replace(/_/g, ' ')}
      </span>
    )
  }

  export function StatusBadge({ status }) {
    const s = status || 'pending'
    const styles = {
      sent:                 'bg-blue-500/10 text-blue-400',
      meeting_requested:    'bg-emerald-500/20 text-emerald-400 font-bold',
      meeting_scheduled:    'bg-emerald-500/15 text-emerald-400',
      meeting_completed:    'bg-purple-500/15 text-purple-400',
      apply_link_received:  'bg-teal-500/20 text-teal-400 font-bold',
      needs_reply:          'bg-yellow-500/20 text-yellow-400 font-bold',
      reply_sent:           'bg-purple-500/10 text-purple-400',
      keep_warm:            'bg-orange-500/10 text-orange-400',
      offer_received:       'bg-emerald-500/30 text-emerald-400 font-bold',
      'archived:rejected':  'bg-red-500/10 text-red-400',
      'archived:bad_email': 'bg-slate-500/10 text-slate-500',
      'archived:no_response':'bg-slate-500/10 text-slate-500',
      'bounce:retry_queued':'bg-orange-500/10 text-orange-400',
    }
    const label = s.replace(/_/g, ' ').replace(':', ' — ')
    return (
      <span className={`text-[11px] px-2 py-0.5 rounded whitespace-nowrap ${styles[s] || 'bg-slate-500/10 text-slate-500'}`}>
        {label}
      </span>
    )
  }

  export function ResponseTypeBadge({ type }) {
    if (!type) return null
    const styles = {
      positive_meeting:    'text-emerald-400',
      positive_apply:      'text-teal-400',
      positive_general:    'text-purple-400',
      negative_no_fit:     'text-red-400',
      negative_no_opening: 'text-orange-400',
    }
    return (
      <span className={`text-xs font-semibold ${styles[type] || 'text-slate-400'}`}>
        {type.replace(/_/g, ' ')}
      </span>
    )
  }
