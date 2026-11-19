export declare const isIOSWebKit: () => boolean;
export declare const iosMomentumOverridesWrites: () => boolean;
export declare const momentumOverridesWrites: () => boolean;
export declare const _resetIOSDetectionForTests: () => void;
type IosTouch = {
    phase: 'down';
    moved: boolean;
} | {
    phase: 'tail';
    moved: boolean;
    awaitingFling: boolean;
    timerId: number;
} | {
    phase: 'lateFling';
    until: number;
} | null;
type TimerWindow = Pick<Window, 'setTimeout' | 'clearTimeout'>;
export declare class IosGesture {
    private readonly host;
    private _touch;
    constructor(host: {
        getWindow: () => TimerWindow | null;
        now: () => number;
        tailStillMoving: () => boolean;
        onTailClosed: () => void;
    });
    get touch(): IosTouch;
    inMotion: () => boolean;
    dragging: () => boolean;
    tail: () => "tap" | "fling" | null;
    onScroll: ({ isScrolling, ownReadBack, moved, external, }: {
        isScrolling: boolean;
        ownReadBack: boolean;
        moved: boolean;
        external: boolean;
    }) => boolean;
    touchStart: () => void;
    touchEnd: () => void;
    end: () => void;
    listen: (target: EventTarget) => () => void;
    private _openTail;
}
export {};
