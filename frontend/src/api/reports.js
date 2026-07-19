// Report analysis API client — POST /api/reports/analyze.
//
// The backend expects the file as base64 JSON (not multipart), so this module
// reads the File via FileReader, strips the `data:<mime>;base64,` prefix that
// readAsDataURL() adds, and sends the raw base64 payload as one field. Same
// auth pattern as the rest of the app: JWT read through getToken(), sent as
// an explicit Authorization header (never a cookie).

import { getToken } from './auth.js'
import { API_BASE } from '../config.js'

/**
 * Thrown when the backend rejects a request with HTTP 401. Mirrors the same
 * class used by api/chat.js, api/profiling.js, etc. so callers can use a
 * single `instanceof AuthError` check regardless of which API module threw.
 */
export class AuthError extends Error {
  constructor(message = 'Your session has expired. Please log in again.') {
    super(message)
    this.name = 'AuthError'
  }
}

// Mirrors the backend's MAX_FILE_BYTES (backend/routers/reports.py) so the
// frontend can reject an oversized file before spending time base64-encoding
// and uploading it, rather than only finding out from a 413 response.
export const MAX_REPORT_FILE_BYTES = 5 * 1024 * 1024

// Mirrors the backend's supported-extension set (backend/routers/reports.py
// extract_report_text()) so the file picker and any client-side pre-check can
// give an immediate, specific error instead of waiting on a 415 response.
// PDF is deliberately excluded — the backend rejects it (see that file for why).
export const SUPPORTED_REPORT_EXTENSIONS = [
  '.docx', '.txt', '.md', '.markdown', '.csv', '.log', '.json', '.html', '.htm',
]

// CONTRACT
// takes:  file (File) — the browser File object to encode
// returns: (Promise<string>) — the file's contents as a bare base64 string (no data: URL prefix)
// throws:  Error — when the file cannot be read
/**
 * Read a File as base64 using FileReader.readAsDataURL, then strip the
 * "data:<mime>;base64," prefix so only the raw base64 payload remains — that
 * bare payload is what the backend's data_base64 field expects.
 *
 * @param {File} file
 * @returns {Promise<string>}
 */
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result || ''
      const commaIdx = result.indexOf(',')
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result)
    }
    reader.onerror = () => reject(new Error('Could not read the selected file.'))
    reader.readAsDataURL(file)
  })
}

// CONTRACT
// takes:  file (File) — the file the officer picked to attach
// returns: (string | null) — a user-facing error message, or null if the file passes basic checks
// throws:  never
/**
 * Client-side pre-check mirroring the backend's own validation (size cap,
 * PDF/unknown-extension rejection). This exists purely for fast, specific
 * feedback before spending a round-trip on something the backend would
 * reject anyway — the backend re-validates independently and remains the
 * source of truth (a client-side check can always be bypassed).
 *
 * @param {File} file
 * @returns {string | null}
 */
export function validateReportFile(file) {
  if (!file) return 'No file selected.'
  if (file.size > MAX_REPORT_FILE_BYTES) {
    return 'File is too large. Maximum size is 5 MB.'
  }
  const lowerName = file.name.toLowerCase()
  if (lowerName.endsWith('.pdf')) {
    return "PDF analysis isn't supported yet. Please upload the report as text, Markdown, or a Word (.docx) file."
  }
  const hasKnownExtension = SUPPORTED_REPORT_EXTENSIONS.some((ext) => lowerName.endsWith(ext))
  if (!hasKnownExtension) {
    return 'Unsupported file type. Please upload a text, Markdown, or Word (.docx) report.'
  }
  return null
}

// CONTRACT
// takes:  file (File) — the report file to upload, sessionId (string) — chat session to attach the analysis to, prompt (string) — optional officer instruction for the analysis
// returns: (Promise<{answer_text: string, extracted_chars: number, file_name: string, warning: string|null}>) — the analysis result
// throws:  AuthError — when the backend returns 401, Error — on 413/415/400/502/network failure with the backend's detail message when available
/**
 * Upload a report file for analysis.
 *
 * POST /api/reports/analyze (JSON: {session_id, prompt, file_name, mime_type, data_base64})
 *
 * @param {File} file
 * @param {string} sessionId
 * @param {string} [prompt]
 * @returns {Promise<{answer_text: string, extracted_chars: number, file_name: string, warning: string|null}>}
 * @throws {AuthError} on 401
 * @throws {Error} on other failures, using the backend's `detail` message when present
 */
export async function analyzeReport(file, sessionId, prompt = '') {
  const dataBase64 = await fileToBase64(file)
  const token = getToken()

  let response
  try {
    response = await fetch(`${API_BASE}/api/reports/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        session_id: sessionId,
        prompt,
        file_name: file.name,
        mime_type: file.type || 'application/octet-stream',
        data_base64: dataBase64,
      }),
    })
  } catch (err) {
    throw new Error('Cannot reach the server. Please try again.')
  }

  if (response.status === 401) {
    throw new AuthError()
  }

  if (!response.ok) {
    let detail = `Report analysis failed (HTTP ${response.status}).`
    try {
      const data = await response.json()
      if (data?.detail) detail = data.detail
    } catch {
      // Keep the generic message if the error body isn't JSON.
    }
    throw new Error(detail)
  }

  return response.json()
}
