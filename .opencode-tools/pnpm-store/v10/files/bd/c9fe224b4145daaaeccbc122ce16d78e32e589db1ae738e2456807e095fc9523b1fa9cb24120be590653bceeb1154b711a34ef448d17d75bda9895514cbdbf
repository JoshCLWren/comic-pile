declare function limitConcurrency<Args extends unknown[], Result>(task: (...args: Args) => Promise<Result>, maximum: number): (...args: Args) => Promise<Result>;

export { limitConcurrency };
