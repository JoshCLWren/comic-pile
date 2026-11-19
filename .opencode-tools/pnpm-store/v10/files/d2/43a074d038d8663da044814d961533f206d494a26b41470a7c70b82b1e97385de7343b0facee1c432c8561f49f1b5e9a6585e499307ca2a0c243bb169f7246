import { Visitor } from 'oxc-parser';
import { collectFirstPropertyValue, collectPropertyValues, getPropertyValues } from '../../typescript/ast-helpers.js';
import { toConfig, toEntryPath, toEntry } from '../../util/input.js';
export const entry = ['**/*.spec.{ts,tsx}', '**/*.e2e.{ts,tsx}'];
export const resolveFromAST = (program, { cwd }) => {
    const inputs = [];
    const srcDir = collectFirstPropertyValue(program, 'srcDir') ?? 'src';
    inputs.push(toEntry(`${srcDir}/**/*.tsx`, { production: true }));
    for (const pattern of entry)
        inputs.push(toEntry(pattern));
    for (const script of collectPropertyValues(program, 'globalScript')) {
        inputs.push(toEntryPath(script, { production: true, dir: cwd }));
    }
    for (const style of collectPropertyValues(program, 'globalStyle')) {
        inputs.push(toEntryPath(style, { production: true, dir: cwd }));
    }
    new Visitor({
        ObjectExpression(node) {
            const typeValues = getPropertyValues(node, 'type');
            if (!typeValues.has('global-style'))
                return;
            for (const input of getPropertyValues(node, 'input'))
                inputs.push(toEntryPath(input, { production: true, dir: cwd }));
        },
    }).visit(program);
    for (const tsconfig of collectPropertyValues(program, 'tsconfig')) {
        inputs.push(toConfig('typescript', tsconfig));
    }
    for (const setup of collectPropertyValues(program, 'setupFilesAfterEnv')) {
        inputs.push(toEntry(setup));
    }
    for (const setup of collectPropertyValues(program, 'setupFiles')) {
        inputs.push(toEntry(setup));
    }
    return inputs;
};
