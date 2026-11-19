import { IMPORT_FLAGS } from '../../constants.js';
import { getPropertyValues } from '../../typescript/ast-helpers.js';
import { dirname, join } from '../../util/path.js';
export function createComponentStyleUrlsVisitor(ctx, isSpecifier) {
    const componentNames = new Set();
    return {
        Program() {
            componentNames.clear();
        },
        ImportDeclaration(node) {
            if (!isSpecifier(node.source?.value))
                return;
            for (const spec of node.specifiers ?? []) {
                if (spec.type === 'ImportSpecifier' &&
                    spec.imported.type === 'Identifier' &&
                    spec.imported.name === 'Component')
                    componentNames.add(spec.local.name);
            }
        },
        ClassDeclaration(node) {
            if (componentNames.size === 0)
                return;
            const dir = dirname(ctx.filePath);
            for (const decorator of node.decorators ?? []) {
                const expr = decorator.expression;
                if (expr?.type !== 'CallExpression')
                    continue;
                if (expr.callee?.type !== 'Identifier' || !componentNames.has(expr.callee.name))
                    continue;
                const arg = expr.arguments?.[0];
                if (arg?.type !== 'ObjectExpression')
                    continue;
                for (const url of getPropertyValues(arg, 'styleUrl'))
                    ctx.addImport(join(dir, url), arg.start, IMPORT_FLAGS.NONE);
                for (const url of getPropertyValues(arg, 'styleUrls'))
                    ctx.addImport(join(dir, url), arg.start, IMPORT_FLAGS.NONE);
            }
        },
    };
}
