import { toModule } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'CSpell';
const enablers = ['cspell'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = [
    'package.json',
    '{.,}cspell.config.{js,cjs,mjs,ts,cts,mts,json,jsonc,yaml,yml,toml}',
    '{.,}cspell.{jsonc,yaml,yml}',
    '.c{s,S}pell.json',
    'c{s,S}pell.json',
    '.vscode/c{s,S}pell.json',
    '.vscode/.cspell.json',
    '.config/{.,}cspell.config.{js,cjs,mjs,ts,cts,mts,json,jsonc,yaml,yml,toml}',
    '.config/.c{s,S}pell.json',
    '.config/c{s,S}pell.json',
    '.config/{.,}cspell.jsonc',
    '.config/cspell.{yaml,yml}',
];
const resolveConfig = config => {
    return [config?.import ?? []].flat().map(id => toModule(id));
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
