import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navigation from './components/Navigation'
import './index.css'

const RollPage = lazy(() => import('./pages/RollPage'))
const RatePage = lazy(() => import('./pages/RatePage'))
const QueuePage = lazy(() => import('./pages/QueuePage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const SessionPage = lazy(() => import('./pages/SessionPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function App() {
  const baseUrl = import.meta.env.BASE_URL || '/'
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) || '/' : baseUrl

  return (
    <BrowserRouter basename={normalizedBase}>
      <main className="container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24">
        <Suspense fallback={<div className="text-center text-slate-500">Loading page...</div>}>
          <Routes>
            <Route path="/" element={<RollPage />} />
            <Route path="/rate" element={<RatePage />} />
            <Route path="/queue" element={<QueuePage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/sessions/:id" element={<SessionPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Suspense>
      </main>
      <Navigation />
    </BrowserRouter>
  )
}

export default App
