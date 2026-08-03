import api from './api'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

export const rollBootstrapApi = {
  get: () => api.get<RollBootstrapResponse>('/roll/bootstrap'),
}
