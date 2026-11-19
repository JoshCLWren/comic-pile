import picomatch from 'picomatch';
import { ROOT_WORKSPACE_NAME } from './constants.js';
import { join, relative } from './util/path.js';
const isWorkspaceSpecificHint = (hint) => hint.type === 'project-extension-unregistered' || hint.type === 'project-extension-excluded';
export const getUnusedIgnorePatternHints = (patterns, context) => {
    const hints = [];
    if (patterns.length === 0)
        return hints;
    const reasons = new Map();
    const pending = new Set(patterns);
    for (const paths of context.filePaths) {
        for (const filePath of paths) {
            if (pending.size === 0)
                break;
            const relativePath = relative(context.cwd, filePath);
            for (const pattern of pending) {
                if (pattern.isMatch(relativePath)) {
                    reasons.set(pattern, 'no-issues');
                    pending.delete(pattern);
                }
            }
        }
    }
    for (const pattern of patterns) {
        for (const hint of pattern.hints) {
            let reason = reasons.get(pattern);
            if (!reason) {
                const base = picomatch.scan(String(hint.identifier)).base;
                const isIgnored = base && context.isGitIgnored(join(context.cwd, hint.workspaceName ?? '', base));
                reason = isIgnored ? 'gitignored' : 'no-matches';
            }
            hints.push({ ...hint, reason });
        }
    }
    return hints;
};
export const settleConfigurationHints = (candidates, context) => {
    const groups = new Map();
    for (const hint of candidates) {
        const key = `${hint.configKey ?? hint.workspaceName}::${hint.type}::${hint.identifier}`;
        const group = groups.get(key);
        if (group) {
            if (hint.workspaceName)
                group.workspaces.add(hint.workspaceName);
        }
        else {
            groups.set(key, { hint, workspaces: new Set(hint.workspaceName ? [hint.workspaceName] : []) });
        }
    }
    const coverage = new Map();
    const hints = [];
    for (const { hint, workspaces } of groups.values()) {
        const { configKey } = hint;
        if (configKey && configKey !== ROOT_WORKSPACE_NAME && !isWorkspaceSpecificHint(hint)) {
            let count = coverage.get(configKey);
            if (count === undefined)
                coverage.set(configKey, (count = context.countWorkspaces(configKey)));
            if (workspaces.size < count)
                continue;
        }
        hints.push(hint);
    }
    return hints;
};
