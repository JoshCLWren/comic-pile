import * as bun from './bun.js';
import * as bunx from './bunx.js';
import * as find from './find.js';
import * as npm from './npm.js';
import * as npx from './npx.js';
import * as nub from './nub.js';
import * as pnpm from './pnpm.js';
import * as pnpx from './pnpx.js';
import * as vp from './vp.js';
import * as yarn from './yarn.js';
const packageManagerResolvers = {
    bun: bun.resolve,
    bunx: bunx.resolve,
    nub: nub.resolve,
    nubx: bunx.resolve,
    npm: npm.resolve,
    npx: npx.resolve,
    pnpm: pnpm.resolve,
    pn: pnpm.resolve,
    pnpx: pnpx.resolve,
    pnx: pnpx.resolve,
    vp: vp.resolve,
    yarn: yarn.resolve,
};
export const isPackageManager = (binary) => binary in packageManagerResolvers;
export default { ...packageManagerResolvers, find: find.resolve };
