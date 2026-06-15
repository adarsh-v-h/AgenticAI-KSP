# Frontend Property Tests

Property-based tests for the chat-history-sidebar feature, using
[fast-check](https://fast-check.dev/) with Vitest.

## Naming convention

Property test files MUST match the pattern:

```
*.property.test.js
```

The Vitest `include` glob in `frontend/vite.config.js`
(`src/**/*.{test,property.test}.{js,jsx}`) collects these files.

Example: `sessionList.property.test.js`

## Iteration minimum

Every property runs a minimum of **100 runs**. Import the shared config helper
to apply this consistently:

```js
import fc from 'fast-check'
import { PROPERTY_CONFIG } from './config'

it('keeps session order descending', () => {
  fc.assert(
    fc.property(arbitrarySessions, (sessions) => {
      // ...assertions...
    }),
    PROPERTY_CONFIG, // { numRuns: 100 }
  )
})
```

To raise the count for a specific property, spread and override:

```js
fc.assert(fc.property(arb, predicate), { ...PROPERTY_CONFIG, numRuns: 500 })
```

## Running

```bash
npm test                # runs all vitest tests once
npm run test:watch      # watch mode
```

## Requirement links

Each property test MUST link to the requirement it validates using the format:

```
**Validates: Requirements 1.2**
```
