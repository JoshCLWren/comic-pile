import { IMPORT_FLAGS } from '../../../constants.js';
import { getStringValue, isStringLiteral } from '../../../typescript/ast-nodes.js';
import { isShadowed } from '../../../typescript/visitors/walk.js';
export function createImportSyncVisitor(ctx) {
    const names = new Set();
    return {
        Program(node) {
            names.clear();
            for (const statement of node.body) {
                if (statement.type !== 'ImportDeclaration' || getStringValue(statement.source) !== '@embroider/macros')
                    continue;
                for (const specifier of statement.specifiers ?? []) {
                    if (specifier.type === 'ImportSpecifier' &&
                        specifier.imported.type === 'Identifier' &&
                        specifier.imported.name === 'importSync') {
                        names.add(specifier.local.name);
                    }
                }
            }
        },
        CallExpression(node) {
            const argument = node.arguments[0];
            if (names.size === 0 ||
                node.callee.type !== 'Identifier' ||
                !names.has(node.callee.name) ||
                isShadowed(node.callee.name, node.callee.start) ||
                !isStringLiteral(argument))
                return;
            ctx.addImport(getStringValue(argument), argument.start, IMPORT_FLAGS.OPAQUE);
        },
    };
}
