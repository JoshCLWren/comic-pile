const collectionsFlag = import.meta.env.VITE_ENABLE_COLLECTIONS

export const collectionsEnabled = collectionsFlag === 'true'
