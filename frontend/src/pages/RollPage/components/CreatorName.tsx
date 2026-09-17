import { Link } from 'react-router-dom'
import { type ComicVineCreator } from '../../../services/api'
import { creatorKeyFor, creatorRoutePath } from '../../../utils/creatorKey'

/**
 * Roll creator row (issue #2030).
 *
 * Creators with a stable #2036 provider id link to the real creator detail
 * route. Creators lacking a stable key stay plain name/role text; identity is
 * never guessed from a display name.
 */
export function CreatorName({ creator }: { creator: ComicVineCreator }) {
  const key = creatorKeyFor(creator)
  const roles =
    creator.roles.length > 0 ? (
      <span className="text-stone-500"> · {creator.roles.join(', ')}</span>
    ) : null

  if (!key) {
    return (
      <p className="text-xs text-stone-300">
        <span className="font-bold">{creator.name}</span>
        {roles}
      </p>
    )
  }

  return (
    <p className="text-xs text-stone-300">
      <Link
        to={creatorRoutePath(key)}
        className="font-bold text-amber-500 hover:text-amber-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 rounded"
        aria-label={`View creator ${creator.name}`}
      >
        {creator.name}
      </Link>
      {roles}
    </p>
  )
}
