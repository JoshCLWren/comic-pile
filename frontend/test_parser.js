
import { parseIssueRange } from './src/utils/issueParser.js';

var testCases = [
    '1-5-10',      // Should be literal according to test
    '1--5',        // Double dash
    '-5',          // Negative with empty left
    '5-',          // Negative with empty right
    'abc-def',     // Non-numeric range
    '1-abc',       // Mixed
    'abc-5'        // Mixed reverse
];

console.log('Frontend results:');
for (var i = 0; i < testCases.length; i++) {
    var caseStr = testCases[i];
    try {
        var result = parseIssueRange(caseStr);
        console.log('  ' + JSON.stringify(caseStr) + ' -> ' + JSON.stringify(result));
    } catch (e) {
        console.log('  ' + JSON.stringify(caseStr) + ' -> EXCEPTION: ' + e.constructor.name + ': ' + e.message);
    }
}
