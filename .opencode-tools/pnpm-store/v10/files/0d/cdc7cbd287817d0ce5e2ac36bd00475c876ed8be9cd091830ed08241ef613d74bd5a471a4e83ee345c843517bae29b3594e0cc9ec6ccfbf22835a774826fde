type ScrollEventKind = 'spurious' | 'readBack' | 'clampedReadBack' | 'clampedEcho' | 'external';
export interface ScrollEventInput {
    offset: number;
    isScrolling: boolean;
    elementMax: number | null;
    holdOffset: number;
    scrollOffset: number | null;
    pendingWrite: {
        target: number;
        smooth: boolean;
        lowMaxes?: Array<number>;
    } | null;
    clampedMaxAtWrite: number | null;
}
export declare function classifyScrollEvent({ offset, isScrolling, elementMax, holdOffset, scrollOffset, pendingWrite, clampedMaxAtWrite, }: ScrollEventInput): ScrollEventKind;
export type ScrollPhase = 'queued' | 'smooth' | 'smoothLanded' | 'smoothFinishing' | 'instant';
export interface RetireInput {
    kind: ScrollEventKind;
    offset: number;
    command: {
        index: number | null;
        phase: ScrollPhase;
        lastTargetOffset: number;
    } | null;
    target: () => number;
}
export declare function externalRetiresCommand({ kind, offset, command, target, }: RetireInput): boolean;
export interface ScrollSample {
    t: number;
    offset: number;
}
export declare function flingSpedUp(samples: ReadonlyArray<ScrollSample>): boolean;
export declare function flingCaught(samples: ReadonlyArray<ScrollSample>): boolean;
export {};
