import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { checkHealth } from './api.js'
import ExtractedImages from './pages/ExtractedImages.jsx'
import RfiCrosscheck from './pages/RfiCrosscheck.jsx'
import TestDataDownloads from './pages/TestDataDownloads.jsx'

export default function App() {
  const [backendOk, setBackendOk] = useState(null)

  useEffect(() => {
    checkHealth().then(setBackendOk).catch(() => setBackendOk(false))
  }, [])

  return (
    <div className="app">
      <nav className="top-nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Test Data Downloads
        </NavLink>
        <NavLink to="/crosscheck" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          RFI Crosscheck
        </NavLink>
        <NavLink to="/dataset" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Image Dataset
        </NavLink>
        <div className="health nav-health">
          Backend:{' '}
          {backendOk === null ? '…' : backendOk ? (
            <span className="ok">connected</span>
          ) : (
            <span className="err">offline — run scripts\start-dev.ps1</span>
          )}
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<TestDataDownloads />} />
        <Route path="/crosscheck" element={<RfiCrosscheck />} />
        <Route path="/dataset" element={<ExtractedImages />} />
      </Routes>
    </div>
  )
}
