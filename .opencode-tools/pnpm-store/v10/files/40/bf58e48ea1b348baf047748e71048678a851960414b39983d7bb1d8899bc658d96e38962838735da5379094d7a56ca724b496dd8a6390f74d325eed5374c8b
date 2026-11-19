import { findProperty } from '../../../typescript/ast-helpers.js';
import { getStringValue, isStringLiteral } from '../../../typescript/ast-nodes.js';
const RAW_QUERY_RE = /(\?|&)raw(?:&|$)/;
export function createImportMetaGlobVisitor(ctx) {
    return {
        CallExpression(node) {
            if (node.callee.type !== 'MemberExpression' ||
                node.callee.computed ||
                node.callee.object.type !== 'MetaProperty' ||
                node.callee.property.name !== 'glob' ||
                node.arguments.length < 1)
                return;
            const arg = node.arguments[0];
            let patterns;
            if (isStringLiteral(arg)) {
                patterns = [getStringValue(arg)];
            }
            else if (arg.type === 'ArrayExpression') {
                patterns = [];
                for (const e of arg.elements) {
                    if (e && isStringLiteral(e))
                        patterns.push(getStringValue(e));
                }
            }
            if (!patterns?.length)
                return;
            const options = node.arguments[1];
            if (options?.type === 'ObjectExpression') {
                const queryNode = findProperty(options, 'query');
                const query = getStringValue(queryNode);
                const isRaw = getStringValue(findProperty(options, 'as')) === 'raw' ||
                    (query !== undefined && RAW_QUERY_RE.test(query.startsWith('?') ? query : `?${query}`)) ||
                    getStringValue(findProperty(queryNode, 'raw')) === '';
                if (isRaw)
                    return ctx.addImportGlob(patterns, { analyzeExports: true });
            }
            ctx.addImportGlob(patterns);
        },
    };
}
