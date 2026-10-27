// Manual test of readingModeLabel function
function readingModeLabel(value) {
  if (!value) return ''
  const normalized = value.trim().toLowerCase()
  console.log(`Input: "${value}", normalized: "${normalized}"`)
  
  if (normalized === 'balanced') return 'Balanced'
  if (normalized === 'light') return 'Light'
  if (normalized === 'deep') return 'Deep'
  if (normalized === 'momentum') return 'Momentum'
  if (normalized === 'familiar') return 'Familiar'
  if (normalized === 'explore') return 'Explore'
  if (normalized === 'random') return 'Random'
  return value.trim()
}

// Test the problematic values
console.log('Testing problematic values:')
console.log(`'deep' -> "${readingModeLabel('deep')}"`)
console.log(`'familiar' -> "${readingModeLabel('familiar')}"`)
console.log()

// Test formatSessionMode function
function formatSessionMode(mode) {
  if (!mode) return ''
  const parts = [readingModeLabel(mode.bandwidth), readingModeLabel(mode.intent)].filter(Boolean)
  return parts.join(' · ')
}

// Test the problematic combination
console.log('Testing problematic combination:')
console.log(`{ bandwidth: 'deep', intent: 'familiar' } -> "${formatSessionMode({ bandwidth: 'deep', intent: 'familiar' })}"`)