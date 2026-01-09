# React Architecture for Comic Pile

## Overview

This document describes the React-based frontend architecture for Comic Pile, a dice-driven comic reading tracker. The frontend uses React with Vite for fast development and builds, Tailwind CSS for styling, and React Query (TanStack Query) for server state management.

## Technology Stack

- **Build Tool**: Vite 7.x - Fast, modern build tool with hot module replacement
- **Framework**: React 19.x - UI library with hooks and concurrent features
- **Routing**: React Router DOM 7.x - Client-side routing
- **HTTP Client**: Axios - Promise-based HTTP client with interceptors
- **State Management**: 
  - React Query (@tanstack/react-query 5.x) - Server state, caching, optimistic updates
  - React Context - Client-side global state (dice selection, session state)
- **Styling**: Tailwind CSS 4.x - Utility-first CSS framework with PostCSS integration
- **Type Safety**: TypeScript support via Vite's JSDoc mode

## Project Structure

```
frontend/
├── src/
│   ├── components/      # Reusable UI components
│   │   ├── Header.jsx  # Navigation, session indicators, die selector
│   │   ├── Footer.jsx  # Optional footer component
│   │   └── Dice3D.jsx  # Three.js 3D dice component (from dice3d.js)
│   ├── pages/          # Route-level page components
│   │   ├── RollPage.jsx      # Single dice, roll button, results
│   │   ├── RatePage.jsx      # Rating form, dice display
│   │   ├── QueuePage.jsx     # Thread list, drag-drop reordering
│   │   ├── HistoryPage.jsx    # Event log, undo buttons
│   │   └── SessionPage.jsx   # Session details, snapshots
│   ├── hooks/          # Custom React hooks
│   │   ├── useThreads.js       # React Query hook for threads
│   │   ├── useSession.js       # React Query hook for session
│   │   ├── useHistory.js       # React Query hook for history/events
│   │   ├── useSnapshots.js     # React Query hook for snapshots
│   │   ├── useDiceLadder.js    # Dice ladder logic
│   │   └── useDice3D.js       # Three.js dice lifecycle
│   ├── services/       # API service layer
│   │   └── api.js      # Axios instance with base URL and interceptors
│   ├── contexts/       # React Context providers
│   │   ├── DiceContext.jsx    # Current die, manual mode, selected thread
│   │   └── SessionContext.jsx # Current session, has_restore_point
│   ├── App.jsx         # Main app component with Router
│   ├── main.jsx        # React entry point
│   └── index.css       # Tailwind CSS imports
├── public/             # Static assets (images, fonts)
├── index.html          # HTML template
├── vite.config.js      # Vite configuration
├── tailwind.config.js  # Tailwind CSS configuration
└── package.json        # NPM dependencies and scripts
```

## Component Hierarchy

```
App (BrowserRouter)
├── DiceContext.Provider
├── SessionContext.Provider
├── QueryClientProvider
└── Routes
    ├── / (RollPage)
    │   ├── Header
    │   ├── Dice3D (3D dice visualization)
    │   └── RollButton
    ├── /rate (RatePage)
    │   ├── Header
    │   ├── Dice3D
    │   └── RatingForm
    ├── /queue (QueuePage)
    │   ├── Header
    │   ├── ThreadList
    │   └── ReorderControls
    ├── /history (HistoryPage)
    │   ├── Header
    │   ├── EventList
    │   └── UndoButton
    └── /sessions/:id (SessionPage)
        ├── Header
        ├── SessionDetails
        └── SnapshotList
```

## Data Flow

### API Service Layer

The `services/api.js` module provides a configured Axios instance:

```javascript
const api = axios.create({
  baseURL: '/api',  // FastAPI backend
  timeout: 10000,
})
```

**Request Interceptor**: Adds authentication headers (future feature)
**Response Interceptor**: Extracts response.data automatically, logs errors

### React Query Integration

React Query manages server state with:

- **Queries** (GET requests):
  - `useThreads()` - Fetch thread list
  - `useSession()` - Fetch current session
  - `useHistory()` - Fetch event history
  - `useSnapshots()` - Fetch restore points

- **Mutations** (POST/PUT/DELETE requests):
  - `useCreateThread()` - Add new thread to queue
  - `useRate()` - Submit rating for current thread
  - `useRoll()` - Roll dice and get result
  - `useDeleteThread()` - Remove thread from queue
  - `useReorderQueue()` - Reorder threads (drag-drop or bulk actions)

**Optimistic Updates**: Mutations update local cache immediately, rollback on error

### Context Providers

**DiceContext**: Client-side state for dice interactions
- `currentDie`: Currently selected die type (d4, d6, d8, d10, d12, d20)
- `manualMode`: Boolean flag for manual mode toggle
- `selectedThreadId`: ID of manually selected thread

**SessionContext**: Global session state
- `currentSession`: Active session object
- `hasRestorePoint`: Boolean flag for undo availability

## URL Patterns

React Router preserves existing URL patterns for bookmarks:

| URL | Component | Description |
|-----|-----------|-------------|
| `/` | RollPage | Default home page with dice roll |
| `/rate` | RatePage | Rating form for selected comic |
| `/queue` | QueuePage | Thread list and reordering |
| `/history` | HistoryPage | Event log with undo functionality |
| `/sessions/:id` | SessionPage | Session details and snapshots |

## Build Pipeline

### Development Mode

```bash
npm run dev
# or
pnpm dev
# or
make dev  # (runs via pyproject.toml scripts)
```

Vite dev server runs on `http://localhost:5173` with HMR (Hot Module Replacement).

### Production Build

```bash
npm run build
# or
pnpm build
```

Vite builds to `../static/react/`:
- `index.html` - Entry HTML with asset references
- `assets/index-*.js` - Bundled JavaScript with hash for caching
- `assets/index-*.css` - Tailwind CSS styles

### FastAPI Integration

FastAPI serves the React build:

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/react", StaticFiles(directory="static/react", html=True), name="react")
```

**Access React App**: `http://localhost:8000/react/`

**API Endpoints**: `http://localhost:8000/api/*` (same backend, no changes needed)

## Migration Strategy

### Phase 1: Architecture & Setup (Complete) ✅
- React app created with Vite
- Tailwind CSS configured
- Build pipeline configured
- FastAPI static file serving
- API service layer created
- React Router configured

### Phase 2: Core Components & Routing (Next)
- Create layout components (Header, Footer)
- Create page components (RollPage, RatePage, QueuePage, HistoryPage, SessionPage)
- Implement navigation between pages
- Preserve URL patterns

### Phase 3: State Management & API Integration (Next)
- Implement React Query hooks for all endpoints
- Create mutations with optimistic updates
- Set up Context providers for global state
- Replace mock data with real API calls

### Phase 4: Migrate 3D Dice & HTMX Interactions (Next)
- Port dice3d.js to React component (Dice3D.jsx)
- Replace HTMX attributes with React event handlers
- Implement real-time updates with React Query refetchInterval

### Phase 5: Remove HTMX & Cleanup (Final)
- Delete Jinja2 templates
- Remove HTMX dependencies
- Update documentation

## Styling Approach

### Tailwind CSS Configuration

```javascript
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

**Content Paths**: Scan all React components for Tailwind class usage

### Mobile-First Design

Following the existing design system:
- Touch targets ≥44px
- Responsive layouts (mobile → tablet → desktop)
- Large buttons for easy tapping

### Existing Design Preservation

Use existing Tailwind classes from Jinja2 templates:
- `bg-yellow-400`, `bg-gray-100` for dice colors
- `text-xl`, `font-bold` for typography
- `rounded-lg`, `shadow-md` for card components
- `flex`, `grid` for layouts

## 3D Dice Component

### Three.js Integration

The Dice3D component wraps the existing `dice3d.js` logic:

```jsx
import { useEffect, useRef } from 'react'

function Dice3D({ dieValue, dieType, isRolling }) {
  const containerRef = useRef(null)

  useEffect(() => {
    // Initialize Three.js scene
    const dice = new Dice3D(containerRef.current, dieType)
    
    // Update die value on prop change
    if (dieValue) {
      dice.setValue(dieValue)
    }

    // Cleanup on unmount
    return () => dice.destroy()
  }, [dieValue, dieType])

  return <div ref={containerRef} className="dice-container" />
}
```

**Lifecycle**: `useEffect` handles Three.js init and cleanup
**Reactivity**: Props trigger dice updates

## Testing Strategy

### Unit Tests

React components can be tested with React Testing Library (future addition):
```javascript
test('roll button calls useRoll mutation', () => {
  const { getByText } = render(<RollPage />)
  fireEvent.click(getByText(/roll d6/i))
  expect(useRoll).toHaveBeenCalled()
})
```

### Integration Tests

Existing Playwright tests will verify:
- Roll flow: Tap roll → See result → Start reading
- Queue management: Add, delete, reorder threads
- History navigation and undo
- Session lifecycle

### API Tests

Existing pytest tests cover backend API endpoints:
```python
async def test_roll_dice(async_client):
    response = await async_client.post("/roll/roll")
    assert response.status_code == 200
    assert "result" in response.json()
```

## Performance Considerations

### Code Splitting

Vite automatically splits code by routes (dynamic imports):
```jsx
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
```

### Caching Strategy

- **React Query**: Cache API responses for 30 seconds (default)
- **Static Assets**: Vite adds hash to filenames (`index-BwiMnkKz.js`)
- **Browser Cache**: Static files cached via FastAPI StaticFiles

### Bundle Size

Initial bundle: ~229 KB (73 KB gzipped)
- Includes React, React Router, Axios, React Query
- Additional 3D dice library (Three.js) loaded on demand

## Development Workflow

### Linting

```bash
npm run lint  # ESLint for JSX/JavaScript
make lint     # Run Python + JavaScript linting
```

### Type Checking

Vite provides JSDoc-based type hints for JavaScript files.

### Hot Reload

Vite dev server updates:
- CSS changes without full reload
- Component updates with HMR (preserves state)

## Deployment

### Build Process

1. `npm run build` → Builds to `static/react/`
2. `alembic upgrade head` → Database migrations
3. `uvicorn app.main:app --host 0.0.0.0` → Start FastAPI

### Environment Variables

No React-specific env vars needed (uses `/api` for backend).

## Key Decisions & Rationale

### Why Vite over Create React App?
- Faster builds (esbuild vs webpack)
- Better HMR (preserves component state)
- Modern config (no webpack config needed)

### Why React Query over Redux?
- Server state management built-in
- Automatic caching and refetching
- Optimistic updates simpler to implement
- Less boilerplate code

### Why Axios over Fetch?
- Request/response interceptors
- Automatic JSON parsing
- Better error handling
- Timeout support

### Why Tailwind CSS 4.x over 3.x?
- New PostCSS plugin (`@tailwindcss/postcss`)
- Faster build times
- Simpler configuration

## Future Enhancements

1. **TypeScript Migration**: Migrate from JSDoc to full TypeScript
2. **Error Boundaries**: Add React error boundaries for graceful failures
3. **Loading States**: Skeleton screens during data fetching
4. **Pagination**: Infinite scroll for large thread queues
5. **Real-time Updates**: WebSocket for live session updates
6. **PWA**: Add service worker for offline support
7. **Accessibility**: ARIA labels, keyboard navigation, screen reader support

## References

- [Vite Documentation](https://vitejs.dev/)
- [React Documentation](https://react.dev/)
- [React Query Documentation](https://tanstack.com/query/latest)
- [Tailwind CSS Documentation](https://tailwindcss.com/)
- [React Router Documentation](https://reactrouter.com/)
- [Comic Pile API Documentation](./API.md)
- [AGENTS.md](../AGENTS.md) - Project guidelines and conventions
