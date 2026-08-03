import type { RollBootstrapThread as RollBootstrapThreadShape } from './rollBootstrap'

export {}

declare module './index' {
  interface RollBootstrapThread extends RollBootstrapThreadShape {}
}
