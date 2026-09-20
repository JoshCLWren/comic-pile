/**
 * True when painted Queue card text mentions `title` as a whole title.
 *
 * Substring checks would treat "Test Thread 40" as a hit for 140 and 240.
 */
export function queueCardMentionsTitle(text: string, title: string): boolean {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`${escaped}(?!\\d)`).test(text)
}
