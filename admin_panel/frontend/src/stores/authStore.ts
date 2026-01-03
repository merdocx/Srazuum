import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { LoginCredentials, Token, Admin } from '../types'
import { api } from '../services/api'

interface AuthState {
  token: string | null
  admin: Admin | null
  isAuthenticated: boolean
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => void
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      admin: null,
      isAuthenticated: false,

      login: async (credentials: LoginCredentials) => {
        const response = await api.post<Token>('/api/auth/login/json', {
          username: credentials.username,
          password: credentials.password,
        })

        const { access_token } = response.data
        set({ token: access_token, isAuthenticated: true })

        // Получаем информацию о текущем администраторе
        await get().fetchMe()
      },

      logout: () => {
        set({ token: null, admin: null, isAuthenticated: false })
      },

      fetchMe: async () => {
        try {
          const response = await api.get<Admin>('/api/auth/me')
          set({ admin: response.data })
        } catch (error) {
          console.error('Failed to fetch admin info:', error)
          get().logout()
        }
      },
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token, isAuthenticated: state.isAuthenticated }),
    }
  )
)

