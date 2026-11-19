import { toIgnore } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { toUnconfig } from '../../util/plugin-config.js';
const title = 'UnoCSS';
const enablers = ['unocss'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = [...toUnconfig('uno.config'), ...toUnconfig('unocss.config')];
const resolve = () => [toIgnore('uno.css', 'dependencies')];
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    resolve,
};
export default plugin;
