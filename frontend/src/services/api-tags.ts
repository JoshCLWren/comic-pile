// Import types from the main types file
import type {
  Tag,
  TagAssignment,
  TagInheritanceSource,
  EffectiveTag,
  TagCreateRequest,
  TagUpdateRequest,
  TagAssignmentRequest,
  TagUsageInfo,
  TagNearMatch,
  TagSearchResult,
  TagTargetType,
  TagBulkOperation,
} from '../types'

export type { TagBulkOperation }

/**
 * API service for tag operations
 */

export class TagsApi {
  private baseUrl = '/api/v1/tags'

  /**
   * List all visible tags (global + user's private)
   */
  async listTags(): Promise<Tag[]> {
    const response = await fetch(this.baseUrl)
    if (!response.ok) {
      throw new Error(`Failed to list tags: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Get specific tag by ID (with visibility enforcement)
   */
  async getTag(id: number): Promise<Tag> {
    const response = await fetch(`${this.baseUrl}/${id}`)
    if (!response.ok) {
      throw new Error(`Failed to get tag ${id}: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Create a new tag
   */
  async createTag(request: TagCreateRequest): Promise<Tag> {
    const response = await fetch(this.baseUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      throw new Error(`Failed to create tag: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Update an existing tag
   */
  async updateTag(id: number, request: TagUpdateRequest): Promise<Tag> {
    const response = await fetch(`${this.baseUrl}/${id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      throw new Error(`Failed to update tag ${id}: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Delete a tag and cascade assignments
   */
  async deleteTag(id: number): Promise<void> {
    const response = await fetch(`${this.baseUrl}/${id}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      throw new Error(`Failed to delete tag ${id}: ${response.statusText}`)
    }
  }

  /**
   * Assign a tag to a target
   */
  async assignTag(id: number, request: TagAssignmentRequest): Promise<TagAssignment> {
    const response = await fetch(`${this.baseUrl}/${id}/assign/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      throw new Error(`Failed to assign tag ${id}: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Remove a tag assignment
   */
  async unassignTag(id: number, request: TagAssignmentRequest): Promise<void> {
    const response = await fetch(`${this.baseUrl}/${id}/unassign/`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })
    if (!response.ok) {
      throw new Error(`Failed to unassign tag ${id}: ${response.statusText}`)
    }
  }

  /**
   * Get tag usage statistics
   */
  async getTagUsage(id: number): Promise<TagUsageInfo> {
    const response = await fetch(`${this.baseUrl}/${id}/usage/`)
    if (!response.ok) {
      throw new Error(`Failed to get tag ${id} usage: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Get effective tags (direct + inherited) for a target
   */
  async getEffectiveTags(type: TagTargetType, id: number): Promise<EffectiveTag[]> {
    const response = await fetch(`${this.baseUrl}/effective/${type.toLowerCase()}/${id}/`)
    if (!response.ok) {
      throw new Error(`Failed to get effective tags for ${type} ${id}: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Search for tags by name (for autocomplete)
   */
  async searchTags(query: string, limit: number = 10): Promise<TagSearchResult[]> {
    const params = new URLSearchParams({ query, limit: String(limit) })
    const response = await fetch(`${this.baseUrl}/search/?${params}`)
    if (!response.ok) {
      throw new Error(`Failed to search tags: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Get near-matches for tag creation (suggestions)
   */
  async getNearMatches(name: string, limit: number = 8): Promise<TagNearMatch[]> {
    const params = new URLSearchParams({ name, limit: String(limit) })
    const response = await fetch(`${this.baseUrl}/near-matches/?${params}`)
    if (!response.ok) {
      throw new Error(`Failed to get near matches: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Bulk assign/remove tags from multiple targets
   */
  async bulkTagOperations(operations: TagBulkOperation[]): Promise<void> {
    const response = await fetch(`${this.baseUrl}/bulk/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ operations }),
    })
    if (!response.ok) {
      throw new Error(`Failed to perform bulk tag operations: ${response.statusText}`)
    }
  }

  /**
   * Check if a tag name is available (normalized comparison)
   */
  async checkNameAvailability(name: string, scope: 'global' | 'private'): Promise<{
    available: boolean
    existing_tag?: Tag
    near_matches?: TagNearMatch[]
  }> {
    const params = new URLSearchParams({ name, scope })
    const response = await fetch(`${this.baseUrl}/check-name/?${params}`)
    if (!response.ok) {
      throw new Error(`Failed to check name availability: ${response.statusText}`)
    }
    return response.json()
  }
}

// Export a singleton instance
export const tagsApi = new TagsApi()