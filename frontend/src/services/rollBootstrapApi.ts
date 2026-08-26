import api from './api'
import type {
  RollBootstrapResponse,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'

export const rollBootstrapApi = {
  get: (timezone?: string) => {
    if (!timezone) return api.get<RollBootstrapResponse>('/v1/roll/bootstrap')
    return api.get<RollBootstrapResponse>('/v1/roll/bootstrap', {
      params: { timezone },
    })
  },
  switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
    api.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
}
