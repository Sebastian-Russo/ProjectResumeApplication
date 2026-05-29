export default function Spinner({ size = 24 }) {
    return (
      <div
        style={{ width: size, height: size }}
        className="border-2 border-[var(--border)] border-t-purple-400 rounded-full animate-spin"
      />
    )
  }
