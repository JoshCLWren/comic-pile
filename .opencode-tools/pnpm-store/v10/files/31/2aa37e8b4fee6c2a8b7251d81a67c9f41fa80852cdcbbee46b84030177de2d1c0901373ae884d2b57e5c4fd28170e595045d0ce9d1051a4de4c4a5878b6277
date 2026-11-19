import { findImportedCalls, findProperty, getStringValues } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { toDependency, toEntry } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { toProviderInput } from '../mdx/index.js';
export const production = ['{src/,}mdx-components.{js,jsx,ts,tsx}'];
export const resolveFromAST = (program, options) => {
    const inputs = production.map(id => toEntry(id, { production: true }));
    const plugins = new Set();
    for (const call of findImportedCalls(program, '@next/mdx')) {
        const mdxOptions = findProperty(call.arguments?.[0], 'options');
        if (mdxOptions?.type !== 'ObjectExpression')
            continue;
        for (const pluginType of ['remarkPlugins', 'rehypePlugins', 'recmaPlugins']) {
            for (const id of getStringValues(findProperty(mdxOptions, pluginType)))
                plugins.add(id);
        }
        const provider = getStringValue(findProperty(mdxOptions, 'providerImportSource'));
        if (provider && !isInternal(provider))
            inputs.push(toProviderInput(provider, options.configFileDir));
    }
    for (const id of plugins)
        inputs.push(toDependency(id));
    return inputs;
};
