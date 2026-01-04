// Auth types
export interface LoginCredentials {
  username: string
  password: string
}

export interface Token {
  access_token: string
  token_type: string
}

export interface Admin {
  id: number
  username: string
  email?: string
  is_active: boolean
  last_login?: string
  created_at: string
}

// API Response types
export interface PaginatedResponse<T> {
  total: number
  skip: number
  limit: number
  data: T[]
}

// Stats types
export interface DashboardStats {
  users: {
    total: number
  }
  links: {
    active: number
  }
  channels: {
    telegram: number
    max: number
    total: number
  }
  messages: {
    total: number
    last_24h: number
    success_24h: number
    failed_24h: number
    unresolved_failed: number
  }
}

// User types
export interface User {
  id: number
  telegram_user_id: number
  telegram_username?: string
  created_at: string
  updated_at: string
  channels_count?: number
  links_count?: number
}

export interface UserDetail extends User {
  telegram_channels: Channel[]
  max_channels: Channel[]
  links: Link[]
}

// Channel types
export interface Channel {
  id: number
  user_id: number
  channel_id: number
  channel_username?: string
  channel_title?: string
  is_active: boolean
  bot_added_at?: string
  links_count?: number
}

// Link types
export interface Link {
  id: number
  user_id: number
  telegram_channel_id: number
  max_channel_id: number
  is_enabled: boolean
  subscription_status?: string
  subscription_type?: string
  subscription_end_date?: string
  free_trial_end_date?: string
  is_first_link?: boolean
  created_at: string
  updated_at: string
}

// Log types
export interface MessageLog {
  id: number
  crossposting_link_id: number
  telegram_message_id: number
  max_message_id?: string
  status: 'pending' | 'success' | 'failed'
  error_message?: string
  message_type?: string
  file_size?: number
  processing_time_ms?: number
  created_at: string
  sent_at?: string
}

export interface FailedMessage {
  id: number
  crossposting_link_id: number
  telegram_message_id: number
  error_message: string
  retry_count: number
  last_retry_at?: string
  created_at: string
  resolved_at?: string
  is_resolved: boolean
}

export interface AuditLog {
  id: number
  user_id: number
  action: string
  entity_type: string
  entity_id: number
  details?: any
  created_at: string
}

// System types
export interface SystemStatus {
  services: Record<string, {
    status: string
    active: boolean
    active_state?: string
    sub_state?: string
    load_state?: string
    error?: string
  }>
  database: {
    status: string
  }
  system: {
    cpu_percent: number
    memory: {
      total: number
      used: number
      percent: number
    }
    disk: {
      total: number
      used: number
      percent: number
    }
  }
}

