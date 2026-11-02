import { useRef, useState } from 'react'
import type { RollBootstrapThread } from '../../types/rollBootstrap'
import type { RatingThread } from './types'

export interface RollPageState {
  isRolling: boolean
  rolledResult: number | null
  selectedThreadId: number | null
  currentDie: number
  diceState: string
  isOverrideOpen: boolean
  overrideThreadId: string
  overrideErrorMessage: string
  snoozedExpanded: boolean
  skippedExpanded: boolean
  isDieModalOpen: boolean
  isSetCurrentIssueOpen: boolean
  selectedThread: RollBootstrapThread | null
  isActionSheetOpen: boolean
  activeRatingThread: RatingThread | null
  showMigrationDialog: boolean
  threadToMigrate: RatingThread | null
  showSimpleMigration: boolean
  isRatingView: boolean
  isShuffleOpen: boolean
  /** Failure feedback rendered inside the open shuffle confirmation. */
  shuffleError: string
  rating: number
  errorMessage: string
  suppressPendingAutoOpenRef: React.MutableRefObject<boolean>
  /**
   * Pending thread id from the last authoritative snapshot that a committed
   * Skip already consumed while its follow-up bootstrap refresh failed.
   * `useRollPendingSession` must ignore that id, because the snapshot on
   * screen still names the series the reader just skipped. The guard clears
   * itself as soon as a newer snapshot reports a different pending read.
   */
  ignoredPendingThreadIdRef: React.MutableRefObject<number | null>
  rollIntervalRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>
  rollTimeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>
}

export interface RollPageStateSetters {
  setIsRolling: (value: boolean) => void
  setRolledResult: (value: number | null) => void
  setSelectedThreadId: (value: number | null) => void
  setCurrentDie: (value: number) => void
  setDiceState: (value: string) => void
  setIsOverrideOpen: (value: boolean) => void
  setOverrideThreadId: (value: string) => void
  setOverrideErrorMessage: (value: string) => void
  setSnoozedExpanded: (value: boolean) => void
  setSkippedExpanded: (value: boolean) => void
  setIsDieModalOpen: (value: boolean) => void
  setIsSetCurrentIssueOpen: (value: boolean) => void
  setSelectedThread: (value: RollBootstrapThread | null) => void
  setIsActionSheetOpen: (value: boolean) => void
  setActiveRatingThread: (value: RatingThread | null) => void
  setShowMigrationDialog: (value: boolean) => void
  setThreadToMigrate: (value: RatingThread | null) => void
  setShowSimpleMigration: (value: boolean) => void
  setIsRatingView: (value: boolean) => void
  setIsShuffleOpen: (value: boolean) => void
  setShuffleError: (value: string) => void
  setRating: (value: number) => void
  setErrorMessage: (value: string) => void
}

export function useRollPageState(): RollPageState & RollPageStateSetters {
  const [isRolling, setIsRolling] = useState(false)
  const [rolledResult, setRolledResult] = useState<number | null>(null)
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [currentDie, setCurrentDie] = useState(6)
  const [diceState, setDiceState] = useState('idle')
  const [isOverrideOpen, setIsOverrideOpen] = useState(false)
  const [overrideThreadId, setOverrideThreadId] = useState('')
  const [overrideErrorMessage, setOverrideErrorMessage] = useState('')
  const [snoozedExpanded, setSnoozedExpanded] = useState(false)
  const [skippedExpanded, setSkippedExpanded] = useState(false)
  const [isDieModalOpen, setIsDieModalOpen] = useState(false)
  const [isSetCurrentIssueOpen, setIsSetCurrentIssueOpen] = useState(false)
  const [selectedThread, setSelectedThread] = useState<RollBootstrapThread | null>(null)
  const [isActionSheetOpen, setIsActionSheetOpen] = useState(false)
  const [activeRatingThread, setActiveRatingThread] = useState<RatingThread | null>(null)
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [threadToMigrate, setThreadToMigrate] = useState<RatingThread | null>(null)
  const [showSimpleMigration, setShowSimpleMigration] = useState(false)
  const [isRatingView, setIsRatingView] = useState(false)
  const [isShuffleOpen, setIsShuffleOpen] = useState(false)
  const [shuffleError, setShuffleError] = useState('')
  const [rating, setRating] = useState(4.0)
  const [errorMessage, setErrorMessage] = useState('')

  const suppressPendingAutoOpenRef = useRef(false)
  const ignoredPendingThreadIdRef = useRef<number | null>(null)
  const rollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const rollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  return {
    isRolling,
    setIsRolling,
    rolledResult,
    setRolledResult,
    selectedThreadId,
    setSelectedThreadId,
    currentDie,
    setCurrentDie,
    diceState,
    setDiceState,
    isOverrideOpen,
    setIsOverrideOpen,
    overrideThreadId,
    setOverrideThreadId,
    overrideErrorMessage,
    setOverrideErrorMessage,
    snoozedExpanded,
    setSnoozedExpanded,
    skippedExpanded,
    setSkippedExpanded,
    isDieModalOpen,
    setIsDieModalOpen,
    isSetCurrentIssueOpen,
    setIsSetCurrentIssueOpen,
    selectedThread,
    setSelectedThread,
    isActionSheetOpen,
    setIsActionSheetOpen,
    activeRatingThread,
    setActiveRatingThread,
    showMigrationDialog,
    setShowMigrationDialog,
    threadToMigrate,
    setThreadToMigrate,
    showSimpleMigration,
    setShowSimpleMigration,
    isRatingView,
    setIsRatingView,
    isShuffleOpen,
    setIsShuffleOpen,
    shuffleError,
    setShuffleError,
    rating,
    setRating,
    errorMessage,
    setErrorMessage,
    suppressPendingAutoOpenRef,
    ignoredPendingThreadIdRef,
    rollIntervalRef,
    rollTimeoutRef,
  }
}