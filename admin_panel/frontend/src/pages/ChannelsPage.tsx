import { useState } from 'react'
import { useQuery } from 'react-query'
import { api } from '../services/api'
import { Channel, PaginatedResponse } from '../types'
import './ChannelsPage.css'

export default function ChannelsPage() {
  const [page, setPage] = useState(0)
  const [type, setType] = useState<'telegram' | 'max'>('telegram')
  const limit = 50

  const { data, isLoading, error } = useQuery<PaginatedResponse<Channel>>(
    ['channels', type, page],
    async () => {
      const response = await api.get(`/api/channels/${type}`, {
        params: {
          skip: page * limit,
          limit,
        },
      })
      return response.data
    }
  )

  if (isLoading) {
    return <div className="page-loading">Загрузка каналов...</div>
  }

  if (error) {
    return <div className="page-error">Ошибка загрузки данных</div>
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0

  return (
    <div className="channels-page">
      <div className="page-header">
        <h1>Каналы</h1>
        <div className="page-controls">
          <div className="tabs">
            <button
              className={type === 'telegram' ? 'active' : ''}
              onClick={() => {
                setType('telegram')
                setPage(0)
              }}
            >
              Telegram
            </button>
            <button
              className={type === 'max' ? 'active' : ''}
              onClick={() => {
                setType('max')
                setPage(0)
              }}
            >
              MAX
            </button>
          </div>
        </div>
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>User ID</th>
              <th>Channel ID</th>
              <th>Username</th>
              <th>Название</th>
              <th>Активен</th>
              <th>Связи</th>
              <th>Добавлен</th>
            </tr>
          </thead>
          <tbody>
            {data?.data.map((channel) => (
              <tr key={channel.id}>
                <td>{channel.id}</td>
                <td>{channel.user_id}</td>
                <td>{channel.channel_id}</td>
                <td>{channel.channel_username || '-'}</td>
                <td>{channel.channel_title || '-'}</td>
                <td>{channel.is_active ? '✓' : '✗'}</td>
                <td>{channel.links_count || 0}</td>
                <td>
                  {channel.bot_added_at
                    ? new Date(channel.bot_added_at).toLocaleString('ru-RU')
                    : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total === 0 && (
        <div className="empty-state">Каналы не найдены</div>
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

