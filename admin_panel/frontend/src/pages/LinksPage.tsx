import { useState } from 'react'
import { useQuery } from 'react-query'
import { api } from '../services/api'
import { Link, PaginatedResponse } from '../types'
import './LinksPage.css'

interface LinkData extends Link {
  telegram_channel?: {
    id: number
    title?: string
    username?: string
  }
  max_channel?: {
    id: number
    title?: string
    username?: string
  }
}

export default function LinksPage() {
  const [page, setPage] = useState(0)
  const limit = 50

  const { data, isLoading, error } = useQuery<PaginatedResponse<LinkData>>(
    ['links', page],
    async () => {
      const response = await api.get('/api/links', {
        params: {
          skip: page * limit,
          limit,
        },
      })
      return response.data
    }
  )

  if (isLoading) {
    return <div className="page-loading">Загрузка связей...</div>
  }

  if (error) {
    return <div className="page-error">Ошибка загрузки данных</div>
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0

  return (
    <div className="links-page">
      <div className="page-header">
        <h1>Связи кросспостинга</h1>
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>User ID</th>
              <th>Telegram канал</th>
              <th>MAX канал</th>
              <th>Активна</th>
              <th>Создана</th>
            </tr>
          </thead>
          <tbody>
            {data?.data.map((link) => (
              <tr key={link.id}>
                <td>{link.id}</td>
                <td>{link.user_id}</td>
                <td>
                  {link.telegram_channel?.title || link.telegram_channel?.username || '-'}
                </td>
                <td>
                  {link.max_channel?.title || link.max_channel?.username || '-'}
                </td>
                <td>{link.is_enabled ? '✓' : '✗'}</td>
                <td>{new Date(link.created_at).toLocaleString('ru-RU')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total === 0 && (
        <div className="empty-state">Связи не найдены</div>
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

