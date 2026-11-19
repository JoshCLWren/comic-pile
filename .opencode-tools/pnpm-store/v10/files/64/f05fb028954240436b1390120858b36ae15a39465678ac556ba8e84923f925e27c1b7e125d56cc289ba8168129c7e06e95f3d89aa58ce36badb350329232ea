import type { Command, CommandArgument, Redirection, Word } from "./internal-types.ts";
export declare class CommandImpl implements Command {
    #private;
    type: "Command";
    pos: number;
    end: number;
    name: Word | undefined;
    prefix: Command["prefix"];
    suffix: Command["suffix"];
    constructor(pos: number, end: number, name: Word | undefined, prefix: Command["prefix"], suffix: Command["suffix"]);
    get args(): CommandArgument[];
    get redirects(): Redirection[];
    toJSON(): Omit<Command, "args" | "redirects">;
}
