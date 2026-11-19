import { type RecordableHistogram } from 'node:perf_hooks';
declare class Performance {
    readonly isEnabled: boolean;
    readonly isTimerifyFunctions: boolean;
    readonly isMemoryUsageEnabled: boolean;
    readonly isDurationEnabled: boolean;
    private startTime;
    private endTime;
    private readonly memId;
    private readonly histograms;
    private readonly memEntries;
    constructor({ isTimerifyFunctions, isMemoryUsageEnabled, isDurationEnabled }: {
        isDurationEnabled?: boolean | undefined;
        isMemoryUsageEnabled?: boolean | undefined;
        isTimerifyFunctions?: boolean | undefined;
    });
    registerHistogram(name: string): RecordableHistogram;
    addMemoryMark(label: string): void;
    getSnapshot(): {
        durationMs: number;
        processMs: number;
        functions: {
            name: string;
            count: number;
            minMs: number;
            maxMs: number;
            meanMs: number;
            medianMs: number;
            p95Ms: number;
            sumMs: number;
        }[];
        memory: {
            label: string;
            heapUsed: number;
            heapTotal: number;
            rss: number;
        }[];
    };
    getTimerifiedFunctionsTable(): string;
    getMemoryUsageTable(): string;
    getCurrentDurationInMs(): number;
    getProcessDurationInMs(): number;
    startRun(): void;
    getMemHeapUsage(): number;
    getCurrentMemUsageInMb(): any;
    finalize(): void;
    reset(): void;
}
export declare const perfObserver: Performance;
export declare const timerify: <T extends (...params: any[]) => any>(fn: T, name?: string) => T;
export {};
