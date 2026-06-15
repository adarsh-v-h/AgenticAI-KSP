// Shared fast-check configuration for chat-history-sidebar property tests.
//
// The project convention is a minimum of 100 runs per property. Import
// PROPERTY_CONFIG and pass it as the second argument to `fc.assert` so every
// property test enforces this minimum consistently.
//
// Example:
//   import fc from 'fast-check'
//   import { PROPERTY_CONFIG } from './config'
//   fc.assert(fc.property(arb, predicate), PROPERTY_CONFIG)

/** Minimum number of generated runs for every property test. */
export const MIN_PROPERTY_RUNS = 100

/** Default fast-check parameters used across the property suite. */
export const PROPERTY_CONFIG = {
  numRuns: MIN_PROPERTY_RUNS,
}
