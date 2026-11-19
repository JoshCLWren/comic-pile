import { isFile } from '../../util/fs.js';
import { toAbsolute } from '../../util/path.js';
const title = 'MCP';
const enablers = 'This plugin is enabled when `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json` or `.codex/config.toml` is found.';
const isRootOnly = true;
const config = ['.mcp.json', '.cursor/mcp.json', '.vscode/mcp.json', '.codex/config.toml'];
const isEnabled = ({ cwd }) => config.some(file => isFile(cwd, file));
const PROJECT_DIR_VAR = /\$\{(?:workspaceFolder|CLAUDE_PROJECT_DIR(?::-[^}]*)?)\}/g;
const resolveConfig = async (localConfig, options) => {
    const { cwd, getInputsFromScripts } = options;
    const servers = { ...localConfig.mcpServers, ...localConfig.servers, ...localConfig.mcp_servers };
    const inputs = [];
    for (const server of Object.values(servers)) {
        if (typeof server?.command !== 'string')
            continue;
        const script = [server.command, ...(server.args ?? [])].join(' ').replace(PROJECT_DIR_VAR, '.');
        const dir = server.cwd ? toAbsolute(server.cwd.replace(PROJECT_DIR_VAR, '.'), cwd) : cwd;
        for (const input of getInputsFromScripts(script, { optionalBinaries: true, cwd: dir })) {
            input.dir = dir;
            inputs.push(input);
        }
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    isRootOnly,
    config,
    resolveConfig,
};
export default plugin;
