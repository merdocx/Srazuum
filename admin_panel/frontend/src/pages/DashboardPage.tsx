import { useQuery } from 'react-query'
import { api } from '../services/api'
import { DashboardStats, SystemStatus } from '../types'
import './DashboardPage.css'

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>(
    'dashboard-stats',
    async () => {
      const response = await api.get('/api/stats/dashboard')
      return response.data
    },
    { refetchInterval: 30000 } // Обновляем каждые 30 секунд
  )

  const { data: systemStatus, isLoading: systemLoading } = useQuery<SystemStatus>(
    'system-status',
    async () => {
      const response = await api.get('/api/system/status')
      return response.data
    },
    { refetchInterval: 10000 } // Обновляем каждые 10 секунд
  )

  if (statsLoading || systemLoading) {
    return <div className="dashboard-loading">Загрузка...</div>
  }

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>
      
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Пользователи</div>
          <div className="stat-value">{stats?.users.total || 0}</div>
        </div>
        
        <div className="stat-card">
          <div className="stat-label">Активные связи</div>
          <div className="stat-value">{stats?.links.active || 0}</div>
        </div>
        
        <div className="stat-card">
          <div className="stat-label">Каналы</div>
          <div className="stat-value">{stats?.channels.total || 0}</div>
          <div className="stat-detail">
            Telegram: {stats?.channels.telegram || 0} | MAX: {stats?.channels.max || 0}
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-label">Сообщений (24ч)</div>
          <div className="stat-value">{stats?.messages.last_24h || 0}</div>
          <div className="stat-detail">
            Успешно: {stats?.messages.success_24h || 0} | Ошибок: {stats?.messages.failed_24h || 0}
          </div>
        </div>
      </div>

      <div className="system-status">
        <h2>Статус сервисов</h2>
        <div className="services-list">
          {systemStatus && Object.entries(systemStatus.services).map(([name, status]) => (
            <div key={name} className={`service-item ${status.active ? 'active' : 'inactive'}`}>
              <span className="service-name">{name}</span>
              <span className="service-status">{status.status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

