import { useState, useRef } from 'react'
import type { Thread, RollResponse, SessionThread } from '../../types'
import type { RatingThread } from './types'

export interface RollPageState {
  isRolling: boolean
  rolledResult: number | null
  selectedThreadId: number | null
  currentDie: number
  diceState: string
  staleThread: (Thread & { days: number }) | null
  staleThreadCount: number
  isOverrideOpen: boolean
  overrideThreadId: string
  snoozedExpanded: boolean
  blockedExpanded: boolean
  isDieModalOpen: boolean
  selectedThread: Thread | null
  isActionSheetOpen: boolean
  activeRatingThread: RatingThread | null
  isCollectionDialogOpen: boolean
  blockingReasonMap: Record<number, string[]>
  showMigrationDialog: boolean
  threadToMigrate: RatingThread | null
  showSimpleMigration: boolean
  isRatingView: boolean
  rating: number
  predictedDie: number
  errorMessage: string
  suppressPendingAutoOpenRef: React.MutableRefObject<boolean>
  rollIntervalRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>
  rollTimeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>
}

export interface RollPageStateSetters {
  setIsRolling: (value: boolean) => void
  setRolledResult: (value: number | null) => void
  setSelectedThreadId: (value: number | null) => void
  setCurrentDie: (value: number) => void
  setDiceState: (value: string) => void
  setStaleThread: (value: (Thread & { days: number }) | null) => void
  setStaleThreadCount: (value: number) => void
  setIsOverrideOpen: (value: boolean) => void
  setOverrideThreadId: (value: string) => void
  setSnoozedExpanded: (value: boolean) => void
  setBlockedExpanded: (value: boolean) => void
  setIsDieModalOpen: (value: boolean) => void
  setSelectedThread: (value: Thread | null) => void
  setIsActionSheetOpen: (value: boolean) => void
  setActiveRatingThread: (value: RatingThread | null) => void
  setIsCollectionDialogOpen: (value: boolean) => void
  setBlockingReasonMap: (value: Record<number, string[]>) => void
  setShowMigrationDialog: (value: boolean) => void
  setThreadToMigrate: (value: RatingThread | null) => void
  setShowSimpleMigration: (value: boolean) => void
  setIsRatingView: (value: boolean) => void
  setRating: (value: number) => void
  setPredictedDie: (value: number) => void
  setErrorMessage: (value: string) => void
}

export function useRollPageState(): RollPageState & RollPageStateSetters {
  const [isRolling, setIsRolling] = useState(false)
  const [rolledResult, setRolledResult] = useState<number | null>(null)
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [currentDie, setCurrentDie] = useState(6)
  const [diceState, setDiceState] = useState('idle')
  const [staleThread, setStaleThread] = useState<(Thread & { days: number }) | null>(null)
  const [staleThreadCount, setStaleThreadCount] = useState(0)
  const [isOverrideOpen, setIsOverrideOpen] = useState(false)
  const [overrideThreadId, setOverrideThreadId] = useState('')
  const [snoozedExpanded, setSnoozedExpanded] = useState(false)
  const [blockedExpanded, setBlockedExpanded] = useState(false)
  const [isDieModalOpen, setIsDieModalOpen] = useState(false)
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [isActionSheetOpen, setIsActionSheetOpen] = useState(false)
  const [activeRatingThread, setActiveRatingThread] = useState<RatingThread | null>(null)
  const [isCollectionDialogOpen, setIsCollectionDialogOpen] = useState(false)
  const [blockingReasonMap, setBlockingReasonMap] = useState<Record<number, string[]>>({})
  const [showMigrationDialog, setShowMigrationDialog] = useState(false)
  const [threadToMigrate, setThreadToMigrate] = useState<RatingThread | null>(null)
  const [showSimpleMigration, setShowSimpleMigration] = useState(false)
  const [isRatingView, setIsRatingView] = useState(false)
  const [rating, setRating] = useState(4.0)
  const [predictedDie, setPredictedDie] = useState(6)
  const [errorMessage, setErrorMessage] = useState('')

  const suppressPendingAutoOpenRef = useRef(false)
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
    staleThread,
    setStaleThread,
    staleThreadCount,
    setStaleThreadCount,
    isOverrideOpen,
    setIsOverrideOpen,
    overrideThreadId,
    setOverrideThreadId,
    snoozedExpanded,
    setSnoozedExpanded,
    blockedExpanded,
    setBlockedExpanded,
    isDieModalOpen,
    setIsDieModalOpen,
    selectedThread,
    setSelectedThread,
    isActionSheetOpen,
    setIsActionSheetOpen,
    activeRatingThread,
    setActiveRatingThread,
    isCollectionDialogOpen,
    setIsCollectionDialogOpen,
    blockingReasonMap,
    setBlockingReasonMap,
    showMigrationDialog,
    setShowMigrationDialog,
    threadToMigrate,
    setThreadToMigrate,
    showSimpleMigration,
    setShowSimpleMigration,
    isRatingView,
    setIsRatingView,
    rating,
    setRating,
    predictedDie,
    setPredictedDie,
    errorMessage,
    setErrorMessage,
    suppressPendingAutoOpenRef,
    rollIntervalRef,
    rollTimeoutRef,
  }
}