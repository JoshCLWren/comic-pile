// Simple test for readingMode functions - no external dependencies
import { readingModeLabel, formatSessionMode } from '../types/rollBootstrap'

function testReadingModeLabel() {
  console.log('=== Testing readingModeLabel function ===')
  
  // Test known values
  const knownValues = [
    { input: 'deep', expected: 'Deep' },
    { input: 'familiar', expected: 'Familiar' },
    { input: 'balanced', expected: 'Balanced' },
    { input: 'light', expected: 'Light' },
    { input: 'momentum', expected: 'Momentum' },
    { input: 'explore', expected: 'Explore' },
    { input: 'random', expected: 'Random' }
  ]
  
  knownValues.forEach(({ input, expected }) => {
    const result = readingModeLabel(input)
    console.log(`✓ readingModeLabel('${input}') -> '${result}' (expected: '${expected}')`)
    if (result !== expected) {
      console.log(`  ERROR: Expected '${expected}', got '${result}'`)
    }
  })
  
  // Test case variations and whitespace
  const variations = [
    { input: 'Deep', expected: 'Deep' },
    { input: 'DEEP', expected: 'Deep' },
    { input: '  deep  ', expected: 'Deep' },
    { input: 'DeEp', expected: 'Deep' }
  ]
  
  variations.forEach(({ input, expected }) => {
    const result = readingModeLabel(input)
    console.log(`✓ readingModeLabel('${input}') -> '${result}' (expected: '${expected}')`)
    if (result !== expected) {
      console.log(`  ERROR: Expected '${expected}', got '${result}'`)
    }
  })
  
  // Test unknown values
  const unknownValues = ['unknown', 'CustomValue']
  unknownValues.forEach(input => {
    const result = readingModeLabel(input)
    console.log(`✓ readingModeLabel('${input}') -> '${result}' (expected: '${input}')`)
    if (result !== input) {
      console.log(`  ERROR: Expected '${input}', got '${result}'`)
    }
  })
  
  // Test null and undefined values
  const nullValues = [null, undefined, '']
  nullValues.forEach(input => {
    const result = readingModeLabel(input as any)
    console.log(`✓ readingModeLabel(${JSON.stringify(input)}) -> '${result}' (expected: '')`)
    if (result !== '') {
      console.log(`  ERROR: Expected '', got '${result}'`)
    }
  })
}

function testFormatSessionMode() {
  console.log('\n=== Testing formatSessionMode function ===')
  
  // Test normal cases
  const normalCases = [
    { input: { bandwidth: 'deep', intent: 'familiar' }, expected: 'Deep · Familiar' },
    { input: { bandwidth: 'balanced', intent: 'balanced' }, expected: 'Balanced · Balanced' },
    { input: { bandwidth: 'light', intent: 'balanced' }, expected: 'Light · Balanced' },
    { input: { bandwidth: 'balanced', intent: 'random' }, expected: 'Balanced · Random' }
  ]
  
  normalCases.forEach(({ input, expected }) => {
    const result = formatSessionMode(input)
    console.log(`✓ formatSessionMode(${JSON.stringify(input)}) -> '${result}' (expected: '${expected}')`)
    if (result !== expected) {
      console.log(`  ERROR: Expected '${expected}', got '${result}'`)
    }
  })
  
  // Test missing values
  const missingCases = [
    { input: { bandwidth: 'deep', intent: null }, expected: 'Deep' },
    { input: { bandwidth: null, intent: 'familiar' }, expected: 'Familiar' },
    { input: { bandwidth: undefined, intent: 'balanced' }, expected: 'Balanced' },
    { input: { bandwidth: 'light', intent: undefined }, expected: 'Light' }
  ]
  
  missingCases.forEach(({ input, expected }) => {
    const result = formatSessionMode(input as any)
    console.log(`✓ formatSessionMode(${JSON.stringify(input)}) -> '${result}' (expected: '${expected}')`)
    if (result !== expected) {
      console.log(`  ERROR: Expected '${expected}', got '${result}'`)
    }
  })
  
  // Test null/undefined mode object
  const nullModeCases = [null, undefined]
  nullModeCases.forEach(input => {
    const result = formatSessionMode(input as any)
    console.log(`✓ formatSessionMode(${JSON.stringify(input)}) -> '${result}' (expected: '')`)
    if (result !== '') {
      console.log(`  ERROR: Expected '', got '${result}'`)
    }
  })
  
  // Test empty strings
  const emptyStringCases = [
    { input: { bandwidth: '', intent: 'familiar' }, expected: 'Familiar' },
    { input: { bandwidth: 'deep', intent: '' }, expected: 'Deep' },
    { input: { bandwidth: '', intent: '' }, expected: '' }
  ]
  
  emptyStringCases.forEach(({ input, expected }) => {
    const result = formatSessionMode(input as any)
    console.log(`✓ formatSessionMode(${JSON.stringify(input)}) -> '${result}' (expected: '${expected}')`)
    if (result !== expected) {
      console.log(`  ERROR: Expected '${expected}', got '${result}'`)
    }
  })
}

// Run all tests
testReadingModeLabel()
testFormatSessionMode()

console.log('\n=== All tests completed ===')