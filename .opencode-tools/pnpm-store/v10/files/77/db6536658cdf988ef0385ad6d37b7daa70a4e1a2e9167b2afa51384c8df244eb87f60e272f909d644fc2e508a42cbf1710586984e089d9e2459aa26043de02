import { join } from '../../util/path.js';
import { isDirectory } from '../../util/fs.js';
import { toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Mastra';
const enablers = ['mastra'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const extensions = '{js,ts}';
const defaultDir = 'src/mastra';
const discoveryCommands = new Set(['dev', 'build']);
const getProductionPatterns = (dir) => {
    const agentRoots = `${dir}/agents/*/*(subagents/*/)`;
    return [
        `${dir}/index.${extensions}`,
        `${dir}/{storage,observability,logger,server,studio}.{js,ts,mjs,mts}`,
        `${dir}/workflows/*.${extensions}`,
        `${dir}/{,agents/*/}tools/**/*.${extensions}`,
        `${agentRoots}{config,instructions,memory,workspace}.${extensions}`,
        `${agentRoots}{tools,scorers,skills,processors/input,processors/output}/*.${extensions}`,
        `${agentRoots}schedules/**/*.${extensions}`,
        `!${dir}/**/*.{test,spec}.${extensions}`,
        `!${dir}/**/__tests__/**`,
    ];
};
const production = getProductionPatterns(defaultDir);
const args = {
    binaries: ['mastra'],
    string: ['dir', 'tools'],
    alias: { dir: ['d'], tools: ['t'] },
    resolveInputs: (parsed, { cwd }) => {
        if (!discoveryCommands.has(parsed._[0]))
            return [];
        const inputs = [];
        if (parsed.dir) {
            for (const pattern of getProductionPatterns(parsed.dir))
                inputs.push(toEntry(pattern, { production: true }));
        }
        if (parsed.tools) {
            for (const tool of String(parsed.tools).split(',')) {
                const specifier = tool.trim();
                if (!specifier)
                    continue;
                const pattern = isDirectory(join(cwd, specifier)) ? `${specifier}/index.${extensions}` : specifier;
                inputs.push(toEntry(pattern, { production: true }));
            }
        }
        return inputs;
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    production,
    args,
};
export default plugin;
