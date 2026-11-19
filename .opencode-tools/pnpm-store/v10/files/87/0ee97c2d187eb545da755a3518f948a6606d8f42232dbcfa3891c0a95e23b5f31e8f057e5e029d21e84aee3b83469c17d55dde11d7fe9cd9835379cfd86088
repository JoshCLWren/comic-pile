import { findImportedCallArg, getPropertyValues } from '../../typescript/ast-helpers.js';
import { toEntry } from '../../util/input.js';
export const resolveFromAST = program => {
    const starlightConfig = findImportedCallArg(program, '@astrojs/starlight');
    if (!starlightConfig)
        return [];
    const inputs = [];
    for (const id of getPropertyValues(starlightConfig, 'components'))
        inputs.push(toEntry(id, { production: true }));
    for (const id of getPropertyValues(starlightConfig, 'customCss'))
        inputs.push(toEntry(id, { production: true }));
    return inputs;
};
