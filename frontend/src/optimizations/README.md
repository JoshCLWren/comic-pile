# Frontend Performance Optimizations

This document summarizes the performance optimizations implemented for the creator, crossover, and cbl-sources views to reduce unnecessary HTTP calls and improve caching efficiency.

## Optimizations Overview

### Creator Views

#### 1. CreatorsPage (`useCreatorsList` hook)
- **Added caching parameters**: `staleTime: 5 * 60 * 1000` (5 minutes), `gcTime: 10 * 60 * 1000` (10 minutes)
- **Benefit**: Reduces redundant API calls for the creator list when users navigate back to the page within the stale time window
- **Impact**: Faster page loads and reduced server load

#### 2. CreatorDetailPage (`useCreatorDetail` hook)
- **Added caching parameters**: `staleTime: 5 * 60 * 1000` (5 minutes), `gcTime: 10 * 60 * 1000` (10 minutes)
- **Benefit**: Prevents refetching creator details when users navigate within the same creator or return to the page
- **Impact**: Smoother navigation experience and reduced API calls

#### 3. CreatorTeamChemistry (`useCreatorTeamChemistry` hook)
- **Added caching parameters**: `staleTime: 10 * 60 * 1000` (10 minutes), `gcTime: 30 * 60 * 1000` (30 minutes)
- **Benefit**: Team chemistry data changes less frequently, so longer stale times are appropriate
- **Impact**: Reduces unnecessary refetches of team chemistry data

#### 4. CreatorComparisonPage (`useCreatorComparison` hook)
- **Added caching parameters**: `staleTime: 10 * 60 * 1000` (10 minutes), `gcTime: 20 * 60 * 1000` (20 minutes)
- **Benefit**: Comparison data is relatively static and benefits from longer cache times
- **Impact**: Faster comparison loads when users switch between different creator comparisons

### Crossover Views

#### 1. CrossoverGroupsList (`useCrossoverGroupsList` hook)
- **Added caching parameters**: `staleTime: 5 * 60 * 1000` (5 minutes), `gcTime: 15 * 60 * 1000` (15 minutes)
- **Benefit**: Reduces redundant calls to fetch crossover groups
- **Impact**: Faster crossover page loads and reduced server load

#### 2. AllThreads (`useAllThreads` hook)
- **Added caching parameters**: `staleTime: 15 * 60 * 1000` (15 minutes), `gcTime: 30 * 60 * 1000` (30 minutes)
- **Benefit**: Thread data changes infrequently, so longer cache times are appropriate
- **Impact**: Reduces unnecessary thread refetches when expanding crossover groups

#### 3. CrossoverIssuesForRange (`useCrossoverIssuesForRange` hook)
- **Added caching parameters**: `staleTime: 10 * 60 * 1000` (10 minutes), `gcTime: 20 * 60 * 1000` (20 minutes)
- **Benefit**: Issue data is relatively static and benefits from longer cache times
- **Impact**: Faster issue loading when working with crossover ranges

### CBL Sources Views

#### 1. CBLBrowseQuery (`CblBrowserPage`)
- **Added caching parameters**: `staleTime: 5 * 60 * 1000` (5 minutes), `gcTime: 15 * 60 * 1000` (15 minutes)
- **Benefit**: Reduces redundant calls when browsing the CBL catalog
- **Impact**: Faster navigation through the catalog and reduced server load

#### 2. CBLPreviewQuery (`CblBrowserPage`)
- **Added caching parameters**: `staleTime: 10 * 60 * 1000` (10 minutes), `gcTime: 20 * 60 * 1000` (20 minutes)
- **Benefit**: Preview data changes less frequently, so longer stale times are appropriate
- **Impact**: Faster preview loads when switching between sources

## Implementation Details

### Caching Strategy
- **Stale Time**: How long data is considered fresh before refetching
- **GC Time**: How long data is kept in memory before garbage collection
- **Differentiated Times**: Different data types have different cache times based on how frequently they change

### Key Benefits
1. **Reduced API Calls**: Fewer redundant HTTP requests to the backend
2. **Faster Navigation**: Pages load faster when navigating back to previously visited pages
3. **Better User Experience**: Smoother interactions with reduced loading states
4. **Reduced Server Load**: Less pressure on backend services
5. **Offline Support**: Better performance when users have limited connectivity

### Testing
All optimizations maintain the existing functionality while improving performance. The changes are backward compatible and don't alter the API contracts.

## Future Optimizations

1. **Prefetching**: Implement intelligent prefetching for likely next views
2. **Batch Loading**: Combine multiple related API calls into single requests
3. **Background Updates**: Refresh data in the background when users are inactive
4. **Smart Invalidation**: More granular cache invalidation based on specific data changes
5. **Compression**: Implement response compression for large data sets