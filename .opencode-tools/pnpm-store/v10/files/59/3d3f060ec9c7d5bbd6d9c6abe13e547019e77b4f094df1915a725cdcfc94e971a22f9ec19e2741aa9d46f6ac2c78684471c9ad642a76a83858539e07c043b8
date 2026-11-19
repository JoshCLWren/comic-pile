import { relative } from '../util/path.js';
import { flattenIssues, getIssueTypeTitle } from './util/util.js';
export default ({ report, issues, cwd, write }) => {
    const lines = ['# Knip report\n'];
    const getFilePath = (issue) => {
        if (!(issue.line && issue.col))
            return relative(cwd, issue.filePath);
        return `${relative(cwd, issue.filePath)}:${issue.line}:${issue.col}`;
    };
    const getSymbol = (issue) => issue.symbol.replaceAll('|', '\\|');
    const sortLongestSymbol = (a, b) => getSymbol(b).length - getSymbol(a).length;
    const sortLongestFilePath = (a, b) => getFilePath(b).length - getFilePath(a).length;
    for (const [reportType, isReportType] of Object.entries(report)) {
        if (isReportType) {
            const title = getIssueTypeTitle(reportType);
            const issuesForType = flattenIssues(issues[reportType]);
            if (issuesForType.length > 0) {
                lines.push(`## ${title} (${issuesForType.length})\n`);
                const longestSymbol = getSymbol(issuesForType.sort(sortLongestSymbol)[0]).length;
                const sortedByFilePath = issuesForType.sort(sortLongestFilePath);
                const longestFilePath = getFilePath(sortedByFilePath[0]).length;
                const nameWidth = Math.max(longestSymbol, 'Name'.length);
                const locationWidth = Math.max(longestFilePath, 'Location'.length);
                lines.push(`| ${'Name'.padEnd(nameWidth)} | ${'Location'.padEnd(locationWidth)} | Severity |`);
                lines.push(`| :${'-'.repeat(nameWidth - 1)} | :${'-'.repeat(locationWidth - 1)} | :------- |`);
                for (const issue of sortedByFilePath) {
                    lines.push(`| ${getSymbol(issue).padEnd(nameWidth)} | ${getFilePath(issue).padEnd(locationWidth)} | ${(issue.severity ?? '').padEnd(8)} |`);
                }
                lines.push('');
            }
        }
    }
    write(lines.join('\n'));
};
