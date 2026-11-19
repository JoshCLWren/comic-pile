export const getAmbiguousStarExport = (resolution, identifier) => {
    if (identifier === 'default')
        return;
    if (resolution.hasExplicitExport || resolution.origins.length < 2)
        return;
    const origins = [];
    for (const origin of resolution.origins) {
        origins.push({ filePath: origin.filePath, identifier: origin.identifier });
    }
    return { origins };
};
