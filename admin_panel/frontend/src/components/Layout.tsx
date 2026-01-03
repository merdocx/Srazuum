import { Routes, Route } from 'react-router-dom'
import Sidebar from './Sidebar'
import DashboardPage from '../pages/DashboardPage'
import UsersPage from '../pages/UsersPage'
import ChannelsPage from '../pages/ChannelsPage'
import LinksPage from '../pages/LinksPage'
import LogsPage from '../pages/LogsPage'
import SystemPage from '../pages/SystemPage'
import './Layout.css'

export default function Layout() {
  return (
    <div className="layout">
      <Sidebar />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/links" element={<LinksPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/system" element={<SystemPage />} />
        </Routes>
      </main>
    </div>
  )
}

