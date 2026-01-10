import { BrowserRouter, Routes, Route } from 'react-router-dom'
import RollPage from './pages/RollPage'
import RatePage from './pages/RatePage'
import QueuePage from './pages/QueuePage'
import HistoryPage from './pages/HistoryPage'
import SessionPage from './pages/SessionPage'
import AnalyticsPage from './pages/AnalyticsPage'
import Navigation from './components/Navigation'
import './index.css'

function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <main className="container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24">
        <Routes>
          <Route path="/" element={<RollPage />} />
          <Route path="/rate" element={<RatePage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/sessions/:id" element={<SessionPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
        </Routes>
      </main>
      <Navigation />
    </BrowserRouter>
  )
}

export default App
