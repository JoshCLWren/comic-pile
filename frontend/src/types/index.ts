export interface ReaderSeriesStats {
  /** Canonical series average rating */
  average_rating: number
  /** Number of rated issues contributing to the average */
  contributing_count: number
  /** Previous issue ID and its effective rating (if available) */
  previous_issue: {
    issue_id: number | null
    effective_rating: number | null
  }
  /** Recent ratings (maximum 5 most recent) */
  recent_ratings: number[]
  /** Highest rating recorded */
  highest_rating: number
  /** Lowest rating recorded */
  lowest_rating: number
}

export interface ReaderCrossoverEntry {
  /** Name of the crossover series */
  name: string
  /** Average rating of the crossover series */
  average_rating: number
  /** Number of rated issues in the crossover */
  rated_count: number
  /** Number of issues read in the crossover */
  read_count: number
  /** Whether this crossover applies to the current issue */
  applies_to_current_issue: boolean
}

export interface ReaderContextResponse {
  /** Canonical series statistics */
  series: ReaderSeriesStats
  /** Crossover analytics panel data */
  crossovers: ReaderCrossoverEntry[]
}