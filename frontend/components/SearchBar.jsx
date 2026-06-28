'use client'

export default function SearchBar({ value, onChange }) {
  return (
    <div className="relative">
      <input
        type="text"
        placeholder="Search endpoints…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded px-3 py-2 pr-8 text-sm"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          aria-label="Clear search"
        >
          ✕
        </button>
      )}
    </div>
  )
}
