import { useState } from 'react'
import { useQuery } from 'react-query'
import { api } from '../services/api'
import { User, PaginatedResponse } from '../types'
import './UsersPage.css'

export default function UsersPage() {
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const limit = 50

  const { data, isLoading, error } = useQuery<PaginatedResponse<User>>(
    ['users', page, search],
    async () => {
      const params = new URLSearchParams({
        skip: (page * limit).toString(),
        limit: limit.toString(),
      })
      if (search) {
        params.append('search', search)
      }
      const response = await api.get(`/api/users?${params}`)
      return response.data
    }
  )

  if (isLoading) {
    return <div className="page-loading">Загрузка пользователей...</div>
  }

  if (error) {
    return <div className="page-error">Ошибка загрузки данных</div>
  }

  const totalPages = data ? Math.ceil(data.total / limit) : 0

  return (
    <div className="users-page">
      <div className="page-header">
        <h1>Пользователи</h1>
        <div className="page-controls">
          <input
            type="text"
            placeholder="Поиск..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
            className="search-input"
          />
        </div>
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Telegram ID</th>
              <th>Username</th>
              <th>Каналы</th>
              <th>Связи</th>
              <th>Дата создания</th>
            </tr>
          </thead>
          <tbody>
            {data?.data.map((user) => (
              <tr key={user.id}>
                <td>{user.id}</td>
                <td>{user.telegram_user_id}</td>
                <td>{user.telegram_username || '-'}</td>
                <td>{user.channels_count || 0}</td>
                <td>{user.links_count || 0}</td>
                <td>{new Date(user.created_at).toLocaleString('ru-RU')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.total === 0 && (
        <div className="empty-state">Пользователи не найдены</div>
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

