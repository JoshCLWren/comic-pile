/** Reader-facing names for the activity types the native resource can emit. */

/** Reader-facing name for a logical action the activity resource emits. */
export function activityLabel(type: string): string {
  switch (type) {
    case 'roll':
      return 'Rolled'
    case 'snooze':
      return 'Snoozed'
    case 'unsnooze':
      return 'Unsnoozed'
    case 'rate':
      return 'Rated'
    case 'manual_die':
      return 'Set die'
    case 'reset_dice':
      return 'Reset die'
    case 'dismiss':
      return 'Dismissed the roll'
    case 'undo':
      return 'Restored'
    case 'rolled_but_skipped':
      return 'Skipped'
    default:
      return type.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
  }
}

/** Types selectable in the History activity-type filter. */
export const ACTIVITY_TYPE_OPTIONS = [
  'roll',
  'snooze',
  'unsnooze',
  'rate',
  'manual_die',
  'reset_dice',
  'dismiss',
  'undo',
  'rolled_but_skipped',
  'read',
  'issue_command',
  'issue_unread',
] as const
