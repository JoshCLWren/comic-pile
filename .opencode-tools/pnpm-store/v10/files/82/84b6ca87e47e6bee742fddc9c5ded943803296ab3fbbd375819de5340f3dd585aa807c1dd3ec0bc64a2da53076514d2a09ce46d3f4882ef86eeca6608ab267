import { importMatcher } from '../../compilers/compilers.js';
const reExport = /\bexport\s+(?:type\s+)?(?:\*(?:\s+as\s+\w+)?|\{[^}]*\})\s+from\s*['"][^'"]+['"]/;
const importSync = /(?<![.\w$])importSync\s*\(\s*['"][^'"]+['"]\s*\)/;
const nonCode = /\/\/[^\r\n]*|\/\*[\s\S]*?\*\/|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`|<template>[\s\S]*?<\/template>/;
const statements = new RegExp(`${importMatcher.source}|${reExport.source}|${importSync.source}|${nonCode.source}`, 'g');
export const compiler = text => {
    const references = [];
    for (const match of text.matchAll(statements)) {
        const statement = match[0];
        if (statement.startsWith('import') || statement.startsWith('export'))
            references.push(statement);
    }
    return references.join(';\n');
};
