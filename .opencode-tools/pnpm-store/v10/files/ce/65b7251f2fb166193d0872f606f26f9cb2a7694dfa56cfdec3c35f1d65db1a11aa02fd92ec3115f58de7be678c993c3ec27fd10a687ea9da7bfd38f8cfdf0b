import { flattenIssues, getColoredTitle, getIssueLine, getIssueTypeTitle } from './util/util.js';
const getIssueRecordLines = (issues, cwd) => {
    const sortedByFilePath = issues.sort((a, b) => (a.filePath > b.filePath ? 1 : -1));
    return sortedByFilePath.map(issue => getIssueLine(issue, cwd));
};
export default ({ report, issues, isShowProgress, cwd, write }) => {
    const lines = [];
    let totalIssues = 0;
    for (const [reportType, isReportType] of Object.entries(report)) {
        if (isReportType) {
            const title = getIssueTypeTitle(reportType);
            const issuesForType = reportType === 'duplicates'
                ? flattenIssues(issues[reportType])
                : Object.values(issues[reportType])
                    .filter(issues => Object.keys(issues).length > 0)
                    .map(issues => {
                    const items = Object.values(issues);
                    return { ...items[0], symbols: items };
                });
            if (issuesForType.length > 0) {
                title && lines.push(getColoredTitle(title, issuesForType.length));
                lines.push(...getIssueRecordLines(issuesForType, cwd));
            }
            totalIssues = totalIssues + issuesForType.length;
        }
    }
    if (totalIssues === 0 && isShowProgress) {
        lines.push('✂️  Excellent, Knip found no issues.');
    }
    write(lines.join('\n'));
};
