import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import './Sidebar.css'

export default function Sidebar() {
  const location = useLocation()
  const { admin, logout } = useAuthStore()

  const menuItems = [
    { path: '/', label: 'Dashboard', icon: '📊' },
    { path: '/users', label: 'Пользователи', icon: '👥' },
    { path: '/channels', label: 'Каналы', icon: '📢' },
    { path: '/links', label: 'Связи', icon: '🔗' },
    { path: '/logs', label: 'Логи', icon: '📝' },
    { path: '/system', label: 'Система', icon: '⚙️' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>Srazuum Admin</h2>
        {admin && (
          <div className="admin-info">
            <div className="admin-name">{admin.username}</div>
          </div>
        )}
      </div>
      <nav className="sidebar-nav">
        {menuItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </Link>
        ))}
      </nav>
      <div className="sidebar-footer">
        <button onClick={logout} className="logout-button">
          Выйти
        </button>
      </div>
    </aside>
  )
}

