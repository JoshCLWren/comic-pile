/**
 * Glossary definition content and anchor contract.
 *
 * Anchor ids are derived from the displayed term instead of being written by
 * hand. Hand-maintained ids drifted away from the terms they were supposed to
 * describe, so deep links such as `/glossary#series` and `/glossary#blocked`
 * silently scrolled nowhere while the stale `/glossary#thread` was the only
 * fragment that worked (issue #3146). Deriving the id makes that divergence
 * unrepresentable; only retired ids stay hand-written, and only as aliases.
 */

export type GlossaryTermDefinition = {
  /**
   * Displayed reader-facing term. The canonical anchor id is the slug of this
   * text, so a card's `#fragment` always matches the term the reader sees.
   */
  term: string
  def: string
  /**
   * Retired anchor ids that stay resolvable so bookmarks, older in-app links,
   * and external deep links written against the previous ids keep landing on
   * this definition.
   */
  aliases?: string[]
}

/** A glossary definition with its derived canonical anchor id. */
export type GlossaryTerm = GlossaryTermDefinition & { id: string }

const DEFINITIONS: GlossaryTermDefinition[] = [
  {
    term: 'Series',
    def: 'One comic series you are tracking, read issue by issue.',
    aliases: ['thread'],
  },
  {
    term: 'Ready to read',
    def: 'Series that can be picked for your next roll right now, because nothing earlier in their reading order is waiting. The Roll page counts these as "N ready to read".',
  },
  {
    term: 'Roll pool',
    def: 'The ready-to-read series a roll picks from.',
  },
  {
    term: 'Auto-adjust',
    def: 'Lets the die pick its own size to match how many series are ready to read. The "Auto" control on Roll turns it back on after you choose a die size by hand.',
    aliases: ['ladder-mode'],
  },
  {
    term: 'Die size',
    def: 'Sets how many series the roll can pick from. Sizes run d4 → d6 → d8 → d10 → d12 → d20 → d30 → d50 → d100, and a larger die includes more of your ready-to-read series. A readout like "d6 → d8" shows the step your die moves after a rating.',
    aliases: ['die-ladder'],
  },
  {
    term: 'Auto',
    def: 'Keeps the die size matched to your ready-to-read series. The "Auto" control on Roll turns this back on after you choose a die size by hand.',
    aliases: ['autoladder'],
  },
  {
    term: 'Offset',
    def: 'Shifts your roll result up or down (e.g. +1 means result+1 is selected).',
  },
  {
    term: 'Snoozed',
    def: 'Temporarily excluded from rolling — won’t appear in the roll pool.',
  },
  {
    term: 'Pos',
    def: 'Queue-order shortcut. "Pos" sorts your series from first to last in the reading queue.',
    aliases: ['position'],
  },
  {
    term: 'Reading mode',
    def: 'How Comic Pile shapes the roll for your mood. Bandwidth sets how demanding comics feel right now (Light, Balanced, Deep); intent sets what kind of pick sounds good (Balanced, Momentum, Familiar, Explore, Random).',
  },
  {
    term: 'Finished series',
    def: 'A series you have read to the end. Finished series stay out of the queue until you add new issues — use the "Add back to queue" action to bring one back.',
  },
  {
    term: 'Dependency rule',
    def: 'A reading order rule: "read X before Y". Create or manage them via the Dependency Builder (open from a series\'s Queue card or from the dependency dialog inside an issue list). Deleting a single rule does not require editing an entire plan.',
    aliases: ['dependency'],
  },
  {
    term: 'Blocked',
    def: 'A comic with an unsatisfied hard prerequisite stays out of the roll pool until that prerequisite is read. Roll is the authority for what can be selected; the product does not ask a second subsystem whether the selected item is ready.',
    aliases: ['readiness'],
  },
  {
    term: 'Crossover',
    def: 'A named group of comics or issues that share one story. Membership labels the group so its continuity is easy to recognize across ComicPile — it does not create a reading block by itself.',
  },
  {
    term: 'Continuity Plan',
    def: 'A saved arrangement of issues, series, and crossovers in one or more reading lanes. Saving creates only the continuity rules you chose — informational plans create none, strict sequential plans create one per step (see Ordering mode).',
  },
  {
    term: 'Ordering mode',
    def: 'What saving a plan commits to. Informational plans create no blocking rules and cannot block anything. Strict sequential plans require you to read each step before the next, compiling one blocking rule per step just like the Dependency Builder. Plan ordering never mixes with the Queue\'s issue-level Dependency Builder unless you choose strict sequential.',
  },
  {
    term: 'Lane',
    def: 'One ordered column of steps inside a continuity plan. Multiple lanes let parallel storylines read side by side.',
  },
  {
    term: 'Reading Order',
    def: 'The saved sequence used to pick what you read. Issues join it as soon as everything before them has been read.',
  },
  {
    term: 'Projection',
    def: 'Applying a continuity plan to a saved reading order. You preview the result first and confirm before it is applied — your plan is never modified.',
  },
  {
    term: 'Dependency Builder',
    def: 'The editable surface for creating, viewing, and removing issue-level dependency rules. Access it from any Queue card (Dependencies in the series actions menu) or from the dependency dialog inside an issue list.',
  },
]

/**
 * Canonical anchor id for a glossary term: lowercase, hyphen-separated, ASCII.
 */
export function slugifyGlossaryTerm(term: string): string {
  return term
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** Every glossary definition, keyed by its canonical term-derived anchor id. */
export const GLOSSARY_TERMS: GlossaryTerm[] = DEFINITIONS.map((definition) => ({
  ...definition,
  id: slugifyGlossaryTerm(definition.term),
}))

/**
 * Every anchor id a deep link may target: canonical ids plus the retired ids
 * kept resolvable for older links.
 */
export const GLOSSARY_ANCHORS: string[] = GLOSSARY_TERMS.flatMap((term) => [
  term.id,
  ...(term.aliases ?? []),
])
