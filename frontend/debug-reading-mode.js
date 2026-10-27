// Debug script to check readingModeLabel function
const { readingModeLabel, formatSessionMode } = require('./src/types/rollBootstrap.ts');

// Test cases from the failing E2E test
const testCases = [
  { bandwidth: 'deep', intent: 'familiar' },
  { bandwidth: 'balanced', intent: 'balanced' },
  { bandwidth: 'light', intent: 'balanced' },
  { bandwidth: 'balanced', intent: 'random' },
  { bandwidth: 'deep', intent: 'explore' },
  { bandwidth: 'deep', intent: 'momentum' },
  { bandwidth: 'deep', intent: 'random' },
  { bandwidth: 'light', intent: 'familiar' }
];

console.log('Testing formatSessionMode function:');
testCases.forEach((mode, index) => {
  const result = formatSessionMode(mode);
  console.log(`Test ${index + 1}:`, mode, '->', result);
});

// Test individual readingModeLabel function
console.log('\nTesting readingModeLabel function:');
const values = ['deep', 'familiar', 'balanced', 'light', 'momentum', 'explore', 'random'];
values.forEach(value => {
  const result = readingModeLabel(value);
  console.log(`readingModeLabel('${value}') -> '${result}'`);
});