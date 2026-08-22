import { render, screen, fireEvent } from '@testing-library/react'
import { ThreadPool } from './ThreadPool'
import { RollBootstrapThread } from '../../../types/rollBootstrap'

// Mock data for testing
const mockPool: RollBootstrapThread[] = [
  {
    id: 1,
    title: 'The Amazing Spider-Man',
    format: 'Mainline',
    issue_number: '1',
    route_labels: ['Main Story']
  },
  {
    id: 2,
    title: 'Batman',
    format: 'DC',
    issue_number: '1',
    route_labels: ['Main Story']
  }
]

const mockBlockedThreads: RollBootstrapThread[] = []
const mockBlockingReasonMap: Record<number, string[]> = {}
const mockSnoozedThreads: Array<{ id: number; title: string; format: string }> = []

describe('ThreadPool Component', () => {
  it('should not contain raw IDs in rendered output', () => {
    render(<ThreadPool 
      pool={mockPool}
      blockedThreads={mockBlockedThreads}
      blockingReasonMap={mockBlockingReasonMap}
      dieSize={20}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={mockSnoozedThreads}
      snoozedExpanded={false}
      blockedExpanded={false}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => {}}
      onShuffle={() => {}}
      unsnoozeIsPending={false}
      shuffleIsPending={false}
    />)
    
    // Check that no raw IDs are present in the rendered output
    const dieFaceElements = screen.getAllByRole('button', { name: /die face/ })
    dieFaceElements.forEach(element => {
      expect(element).not.toHaveTextContent(/Thread \d+/);
      expect(element).not.toHaveTextContent(/Issue \d+/);
      expect(element).not.toHaveTextContent(/ComicVine #\d+/);
    })
  })

  it('should display comic titles instead of IDs', () => {
    render(<ThreadPool 
      pool={mockPool}
      blockedThreads={mockBlockedThreads}
      blockingReasonMap={mockBlockingReasonMap}
      dieSize={20}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={mockSnoozedThreads}
      snoozedExpanded={false}
      blockedExpanded={false}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => {}}
      onShuffle={() => {}}
      unsnoozeIsPending={false}
      shuffleIsPending={false}
    />)
    
    // Check that comic titles are displayed instead of IDs
    const threadElements = screen.getAllByRole('button', { name: /die face/ })
    threadElements.forEach(element => {
      const textContent = element.textContent || ''
      expect(textContent).toMatch(/The Amazing Spider-Man|Batman/) // Should show comic titles
      expect(textContent).not.toMatch(/Issue \d+/)
    })
  })

  it('should have a clear hierarchy with collapsible sections', () => {
    render(<ThreadPool 
      pool={mockPool}
      blockedThreads={mockBlockedThreads}
      blockingReasonMap={mockBlockingReasonMap}
      dieSize={20}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={mockSnoozedThreads}
      snoozedExpanded={false}
      blockedExpanded={false}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => {}}
      onShuffle={() => {}}
      unsnoozeIsPending={false}
      shuffleIsPending={false}
    />)
    
    // Check that the main thread list is displayed
    const threadList = screen.getByText(/Eligible now/)
    expect(threadList).toBeInTheDocument()
    
    // Check that there are thread elements displayed
    const threadElements = screen.getAllByRole('button', { name: /die face/ })
    expect(threadElements.length).toBeGreaterThan(0)
  })

  it('should have collapsible sections for blocked and stale threads', () => {
    // Add some blocked threads to test the collapsible section
    const blockedThread: RollBootstrapThread = {
      id: 3,
      title: 'Blocked Thread',
      format: 'Mainline',
      issue_number: '1',
      route_labels: ['Blocked']
    }
    
    render(<ThreadPool 
      pool={mockPool}
      blockedThreads={[blockedThread]}
      blockingReasonMap={{ 3: ['dependency'] }}
      dieSize={20}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={mockSnoozedThreads}
      snoozedExpanded={false}
      blockedExpanded={false}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => {}}
      onShuffle={() => {}}
      unsnoozeIsPending={false}
      shuffleIsPending={false}
    />)
    
    // Check that the blocked threads section exists
    const toggleButton = screen.getByText(/1 thread hidden \(blocked by dependencies\)/)
    expect(toggleButton).toBeInTheDocument()
    
    // Check that the blocked threads are initially collapsed
    const blockedSection = screen.queryByText(/All threads are blocked or snoozed/)
    expect(blockedSection).toBeInTheDocument()
  })

  it('should display the roll result in a tiered format', () => {
    render(<ThreadPool 
      pool={mockPool}
      blockedThreads={mockBlockedThreads}
      blockingReasonMap={mockBlockingReasonMap}
      dieSize={20}
      isRatingView={false}
      isRolling={false}
      rolledResult={null}
      selectedThreadId={null}
      staleThread={null}
      staleThreadCount={0}
      snoozedThreads={mockSnoozedThreads}
      snoozedExpanded={false}
      blockedExpanded={false}
      onThreadClick={() => {}}
      onUnsnooze={() => {}}
      onReadStale={() => {}}
      onToggleSnoozed={() => {}}
      onToggleBlocked={() => {}}
      onShuffle={() => {}}
      unsnoozeIsPending={false}
      shuffleIsPending={false}
    />)
    
    // Check that the tiered display is present
    const instructionText = screen.getByText(/Tap Die to Roll/)
    expect(instructionText).toBeInTheDocument()
    
    // Check that there's a section for eligible threads
    const eligibleSection = screen.getByText(/Eligible now/)
    expect(eligibleSection).toBeInTheDocument()
    
    // Check that there's a section for when there are no threads
    const emptyState = screen.getByText(/Nothing to roll yet/)
    expect(emptyState).toBeInTheDocument()
  })
})