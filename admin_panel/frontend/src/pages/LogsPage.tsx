import { useState } from 'react'
import { useQuery } from 'react-query'
import { api } from '../services/api'
import { MessageLog, PaginatedResponse } from '../types'
import './LogsPage.css'

export default function LogsPage() {
  const [page, setPage] = useState(0)
  const [type, setType] = useState<'messages' | 'failed' | 'audit'>('messages')
  const limit = 50

  const { data, isLoading, error } = useQuery<PaginatedResponse<MessageLog>>(
    ['logs', type, page],
    async () => {
      const endpoint = type === 'failed' ? '/api/logs/failed' : '/api/logs/messages'
      const response = await api.get(endpoint, {
        params: {
          skip: page * limit,
          limit,
        },
      })
      return response.data
    },
    { enabled: type !== 'audit' }
  )

  if (isLoading) {
    return <div className="page-loading">Загрузка логов...</div>
  }

  if (error) {
    return <div className="page-error">Ошибка загрузки данных</div>
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0

  return (
    <div className="logs-page">
      <div className="page-header">
        <h1>Логи</h1>
        <div className="page-controls">
          <div className="tabs">
            <button
              className={type === 'messages' ? 'active' : ''}
              onClick={() => {
                setType('messages')
                setPage(0)
              }}
            >
              Сообщения
            </button>
            <button
              className={type === 'failed' ? 'active' : ''}
              onClick={() => {
                setType('failed')
                setPage(0)
              }}
            >
              Ошибки
            </button>
            <button
              className={type === 'audit' ? 'active' : ''}
              onClick={() => {
                setType('audit')
                setPage(0)
              }}
              disabled
            >
              Аудит (скоро)
            </button>
          </div>
        </div>
      </div>

      {type === 'messages' && (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Link ID</th>
                <th>Telegram MSG ID</th>
                <th>MAX MSG ID</th>
                <th>Статус</th>
                <th>Тип</th>
                <th>Ошибка</th>
                <th>Создано</th>
              </tr>
            </thead>
            <tbody>
              {data?.data.map((log: any) => (
                <tr key={log.id}>
                  <td>{log.id}</td>
                  <td>{log.crossposting_link_id}</td>
                  <td>{log.telegram_message_id}</td>
                  <td>{log.max_message_id || '-'}</td>
                  <td>
                    <span className={`status-badge status-${log.status}`}>
                      {log.status}
                    </span>
                  </td>
                  <td>{log.message_type || '-'}</td>
                  <td className="error-cell">
                    {log.error_message ? (
                      <span title={log.error_message}>
                        {log.error_message.substring(0, 50)}...
                      </span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td>{new Date(log.created_at).toLocaleString('ru-RU')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {type === 'failed' && (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Link ID</th>
                <th>Telegram MSG ID</th>
                <th>Ошибка</th>
                <th>Попыток</th>
                <th>Создано</th>
                <th>Решено</th>
              </tr>
            </thead>
            <tbody>
              {data?.data.map((log: any) => (
                <tr key={log.id}>
                  <td>{log.id}</td>
                  <td>{log.crossposting_link_id}</td>
                  <td>{log.telegram_message_id}</td>
                  <td className="error-cell" title={log.error_message}>
                    {log.error_message.substring(0, 100)}...
                  </td>
                  <td>{log.retry_count || 0}</td>
                  <td>{new Date(log.created_at).toLocaleString('ru-RU')}</td>
                  <td>{log.resolved_at ? new Date(log.resolved_at).toLocaleString('ru-RU') : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total === 0 && (
        <div className="empty-state">Логи не найдены</div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            Предыдущая
          </button>
          <span>
            Страница {page + 1} из {totalPages} (Всего: {data?.total || 0})
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            Следующая
          </button>
        </div>
      )}
    </div>
  )
}

