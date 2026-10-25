import { useLocation, useNavigate } from 'react-router-dom'

export function LocationProbe() {
  const location = useLocation()
  return (
    <>
      <p data-testid="location">{location.pathname}</p>
      <p data-testid="location-search">{location.search}</p>
    </>
  )
}

/** Simulates the browser Back control that skips the page's own handlers. */
export function HistoryBackProbe() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(-1)}>
      history-back
    </button>
  )
}

