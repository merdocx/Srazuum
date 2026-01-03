import { useQuery } from 'react-query'
import { api } from '../services/api'
import { SystemStatus } from '../types'
import './SystemPage.css'

export default function SystemPage() {
  const { data, isLoading, error } = useQuery<SystemStatus>(
    'system-status',
    async () => {
      const response = await api.get('/api/system/status')
      return response.data
    },
    { refetchInterval: 10000 }
  )

  if (isLoading) {
    return <div className="page-loading">Загрузка системной информации...</div>
  }

  if (error) {
    return <div className="page-error">Ошибка загрузки данных</div>
  }

  const formatBytes = (bytes: number) => {
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    if (bytes === 0) return '0 B'
    const i = Math.floor(Math.log(bytes) / Math.log(1024))
    return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
  }

  return (
    <div className="system-page">
      <h1>Система</h1>

      <div className="system-section">
        <h2>Сервисы</h2>
        <div className="services-grid">
          {data &&
            Object.entries(data.services).map(([name, status]) => (
              <div
                key={name}
                className={`service-card ${status.active ? 'active' : 'inactive'}`}
              >
                <div className="service-name">{name}</div>
                <div className="service-status">
                  <span className={`status-indicator ${status.active ? 'active' : 'inactive'}`} />
                  {status.status}
                </div>
                {status.sub_state && (
                  <div className="service-substate">{status.sub_state}</div>
                )}
              </div>
            ))}
        </div>
      </div>

      <div className="system-section">
        <h2>База данных</h2>
        <div className="info-card">
          <div className="info-label">Статус</div>
          <div className={`info-value ${data?.database.status === 'connected' ? 'success' : 'error'}`}>
            {data?.database.status || 'unknown'}
          </div>
        </div>
      </div>

      {data?.system && (
        <div className="system-section">
          <h2>Ресурсы системы</h2>
          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-label">CPU</div>
              <div className="metric-value">{data.system.cpu_percent.toFixed(1)}%</div>
              <div className="metric-bar">
                <div
                  className="metric-bar-fill"
                  style={{ width: `${data.system.cpu_percent}%` }}
                />
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-label">Память</div>
              <div className="metric-value">{data.system.memory.percent.toFixed(1)}%</div>
              <div className="metric-detail">
                {formatBytes(data.system.memory.used)} / {formatBytes(data.system.memory.total)}
              </div>
              <div className="metric-bar">
                <div
                  className="metric-bar-fill"
                  style={{ width: `${data.system.memory.percent}%` }}
                />
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-label">Диск</div>
              <div className="metric-value">{data.system.disk.percent.toFixed(1)}%</div>
              <div className="metric-detail">
                {formatBytes(data.system.disk.used)} / {formatBytes(data.system.disk.total)}
              </div>
              <div className="metric-bar">
                <div
                  className="metric-bar-fill"
                  style={{ width: `${data.system.disk.percent}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

