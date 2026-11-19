import { createOwnershipEngine } from '../util/codeowners.js';
import { relative, resolve } from '../util/path.js';
import { getColoredTitle, getIssueLine, getIssueTypeTitle } from './util/util.js';
const getIssueRecordLines = (issues, cwd) => {
    const sortedByFilePath = issues.sort((a, b) => (a.owner < b.owner ? -1 : 1));
    return sortedByFilePath.map(({ filePath, symbols, owner, parentSymbol }) => getIssueLine({ owner, filePath, symbols, parentSymbol }, cwd));
};
export default ({ report, issues, isShowProgress, options, cwd, write }) => {
    const lines = [];
    let opts = {};
    try {
        opts = options ? JSON.parse(options) : opts;
    }
    catch (error) {
        console.error(error);
    }
    const codeownersFilePath = resolve(opts.path ?? '.github/CODEOWNERS');
    const findOwners = createOwnershipEngine(codeownersFilePath);
    const reportMultipleGroups = Object.values(report).filter(Boolean).length > 1;
    const [dependenciesOwner = '[no-owner]'] = findOwners('package.json');
    let totalIssues = 0;
    const calcFileOwnership = (filePath) => findOwners(relative(cwd, filePath))[0] ?? dependenciesOwner;
    const addOwner = (issue) => ({
        ...issue,
        owner: calcFileOwnership(issue.filePath),
    });
    for (const [reportType, isReportType] of Object.entries(report)) {
        if (isReportType) {
            const title = reportMultipleGroups && getIssueTypeTitle(reportType);
            const issuesForType = Object.values(issues[reportType]).flatMap(issues => {
                if (reportType === 'duplicates')
                    return Object.values(issues).map(addOwner);
                const symbols = Object.values(issues);
                return addOwner({ ...symbols[0], symbols });
            });
            if (issuesForType.length > 0) {
                if (totalIssues)
                    lines.push('');
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
