import { hasDependency } from '../../util/plugin.js';
const title = 'Lost Pixel';
const enablers = ['lost-pixel'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['lostpixel.config.{js,ts}'];
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
};
export default plugin;
