// Simple test to verify the HistoryPage logic changes
import { buildActivityLine, formatDiceProgression } from './src/pages/HistoryPage.js';

// Mock session data
const mockSession = {
  id: 11,
  started_at: '2024-08-23T10:00:00Z',
  ended_at: '2024-08-23T10:45:00Z',
  ladder_path: '6 → 4 → 6',
  active_thread: {
    title: 'Cable',
    format: 'Comic',
    next_issue_number: '62',
    issues_read: 1,
    last_rating: 4.5,
  },
  last_rolled_result: 3,
  current_die: 6,
  snapshot_count: 2,
};

// Test buildActivityLine
const activityLine = buildActivityLine(mockSession);
console.log('Activity line:', activityLine);

// Test formatDiceProgression
const diceProgression = formatDiceProgression(mockSession.ladder_path, mockSession.last_rolled_result);
console.log('Dice progression:', diceProgression);

// Expected results
const expectedActivityLine = '1 issue read · rated 4.5 · Die size d6';
const expectedDiceProgression = 'd6 → d4 → d6 · Rolled 3';

console.log('\nValidation:');
console.log('Activity line correct:', activityLine === expectedActivityLine);
console.log('Dice progression correct:', diceProgression === expectedDiceProgression);