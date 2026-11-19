import { isDefinitelyTyped } from '../util/modules.js';
import { timerify } from '../util/Performance.js';
import { loadPackageManifest } from './helpers.js';
const getMetaDataFromPackageJson = ({ dir, packageNames }) => {
    const hostDependencies = new Map();
    const installedBinaries = new Map();
    const hasTypesIncluded = new Set();
    const uninstalledDependencies = new Set();
    const addBinary = (key, value) => {
        const set = installedBinaries.get(key);
        if (set)
            set.add(value);
        else
            installedBinaries.set(key, new Set([value]));
    };
    for (const packageName of packageNames) {
        const manifest = loadPackageManifest({ dir, packageName });
        if (manifest) {
            const binaries = typeof manifest.bin === 'string' ? [packageName] : Object.keys(manifest.bin ?? {});
            for (const binaryName of binaries)
                addBinary(binaryName.replace(/^@[^/]+\//, ''), packageName);
            const packagePeerDependencies = Object.keys(manifest.peerDependencies ?? {});
            for (const packagePeerDependency of packagePeerDependencies) {
                const hostDependency = {
                    name: packageName,
                    isPeerOptional: manifest.peerDependenciesMeta?.[packagePeerDependency]?.optional ?? false,
                };
                if (hostDependencies.has(packagePeerDependency)) {
                    hostDependencies.get(packagePeerDependency)?.push(hostDependency);
                }
                else {
                    hostDependencies.set(packagePeerDependency, [hostDependency]);
                }
            }
            if (!isDefinitelyTyped(packageName) && (manifest.types || manifest.typings))
                hasTypesIncluded.add(packageName);
        }
        else {
            uninstalledDependencies.add(packageName);
        }
    }
    return {
        hostDependencies,
        installedBinaries,
        hasTypesIncluded,
        uninstalledDependencies,
    };
};
export const getDependencyMetaData = timerify(getMetaDataFromPackageJson);
