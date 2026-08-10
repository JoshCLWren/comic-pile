import api from './api'
import type {
  RollBootstrapResponse,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'

export const rollBootstrapApi = {
  get: () => api.get<RollBootstrapResponse>('/v1/roll/bootstrap'),
  switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
    api.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
}
