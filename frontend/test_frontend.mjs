
import { parseIssueRange } from './src/utils/issueParser';

console.log('Testing 1-5-10:');
try {
    const result = parseIssueRange('1-5-10');
    console.log('Result:', result);
} catch (e) {
    console.log('Exception:', e.constructor.name, ':', e.message);
}

