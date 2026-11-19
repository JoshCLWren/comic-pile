export type Check<T> = (value: unknown, path: string, errors: string[]) => value is T;
export type Fields<T> = {
    [K in keyof T]-?: Check<Exclude<T[K], undefined>>;
};
export declare const invalid: (path: string, errors: string[], expected?: string, key?: string) => boolean;
export declare const isObject: (value: unknown) => value is Record<string, unknown>;
export declare const checkString: Check<string>;
export declare const checkBoolean: Check<boolean>;
export declare const checkArray: <T>(check: Check<T>) => Check<T[]>;
export declare const checkRecord: <T>(check: Check<T>, isKey?: (key: string) => boolean) => Check<Record<string, T>>;
export declare const checkObject: (value: unknown, path: string, errors: string[], fields: Record<string, Check<unknown>>, extraFields?: 'reject' | 'ignore' | ((key: string) => Check<unknown> | undefined)) => boolean;
