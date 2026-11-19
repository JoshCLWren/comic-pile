import { readFileSync } from 'node:fs';
import { collectStringLiterals } from '../typescript/ast-helpers.js';
import { isDeferResolve, isDependency } from './input.js';
import { getPackageNameFromSpecifier } from './modules.js';
import { dirname, isInternal, join } from './path.js';
const readFile = (filePath) => {
    try {
        return readFileSync(filePath, 'utf8');
    }
    catch {
        return undefined;
    }
};
export const filterTransitiveDependencies = (inputs, configFilePath, readRawFile = readFile) => {
    const literals = new Set();
    const visited = new Set();
    const collect = (filePath) => {
        if (visited.has(filePath))
            return;
        visited.add(filePath);
        const sourceText = readRawFile(filePath);
        if (!sourceText)
            return;
        for (const literal of collectStringLiterals(sourceText, filePath)) {
            literals.add(literal);
            if (isInternal(literal))
                collect(join(dirname(filePath), literal));
        }
    };
    collect(configFilePath);
    for (const input of inputs) {
        if (!input.optional && (isDeferResolve(input) || isDependency(input))) {
            const name = getPackageNameFromSpecifier(input.specifier);
            if (name && !literals.has(name))
                input.optional = true;
        }
    }
};
