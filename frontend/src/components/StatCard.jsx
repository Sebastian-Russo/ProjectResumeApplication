export default function StatCard({ label, value, color = 'purple', active, onClick }) {
    const colors = {
      purple: 'text-purple-400',
      blue:   'text-blue-400',
      green:  'text-emerald-400',
      teal:   'text-teal-400',
      yellow: 'text-yellow-400',
      orange: 'text-orange-400',
      red:    'text-red-400',
      pink:   'text-pink-400',
      gray:   'text-slate-400',
    }
    return (
      <button
        onClick={onClick}
        className={`flex flex-col items-center px-3 py-2 rounded-lg border transition-all min-w-[72px]
          ${active
            ? 'border-purple-500/60 bg-purple-500/8'
            : 'border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--border-hover)]'}`}
      >
        <span className={`text-2xl font-bold leading-none ${colors[color]}`}>{value ?? 0}</span>
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mt-1">{label}</span>
      </button>
    )
  }
