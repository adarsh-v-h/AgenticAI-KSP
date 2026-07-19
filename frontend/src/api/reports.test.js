// Unit tests for api/reports.js — file-size/type pre-validation and the
// analyzeReport() upload flow (base64 encoding, auth header, error surfacing).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { analyzeReport, validateReportFile, AuthError, MAX_REPORT_FILE_BYTES } from './reports.js'
import * as authModule from './auth.js'

function makeFile(name, content = 'hello world', type = 'text/plain') {
  return new File([content], name, { type })
}

describe('validateReportFile', () => {
  it('rejects when no file is provided', () => {
    expect(validateReportFile(null)).toMatch(/no file/i)
  })

  it('rejects files over the 5 MB cap', () => {
    const bigFile = new File([new Uint8Array(MAX_REPORT_FILE_BYTES + 1)], 'big.txt', {
      type: 'text/plain',
    })
    expect(validateReportFile(bigFile)).toMatch(/too large/i)
  })

  it('rejects PDFs with the "not supported yet" message', () => {
    const pdf = makeFile('report.pdf', 'content', 'application/pdf')
    expect(validateReportFile(pdf)).toMatch(/PDF analysis isn't supported/i)
  })

  it('rejects unknown extensions', () => {
    const exe = makeFile('malware.exe', 'content', 'application/octet-stream')
    expect(validateReportFile(exe)).toMatch(/unsupported file type/i)
  })

  it('accepts a supported .txt file', () => {
    expect(validateReportFile(makeFile('notes.txt'))).toBeNull()
  })

  it('accepts a supported .docx file', () => {
    expect(validateReportFile(makeFile('report.docx', 'x', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))).toBeNull()
  })
})

describe('analyzeReport', () => {
  beforeEach(() => {
    vi.spyOn(authModule, 'getToken').mockReturnValue('test-jwt-token')
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sends the base64-encoded file, session id, and prompt to the backend', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer_text: 'Analysis complete.',
        extracted_chars: 42,
        file_name: 'notes.txt',
        warning: null,
      }),
    })

    const file = makeFile('notes.txt', 'Incident report: theft in Koramangala.')
    const result = await analyzeReport(file, 'sess-123', 'focus on repeat offenders')

    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url, options] = global.fetch.mock.calls[0]
    expect(url).toContain('/api/reports/analyze')
    expect(options.method).toBe('POST')
    expect(options.headers.Authorization).toBe('Bearer test-jwt-token')

    const body = JSON.parse(options.body)
    expect(body.session_id).toBe('sess-123')
    expect(body.prompt).toBe('focus on repeat offenders')
    expect(body.file_name).toBe('notes.txt')
    // data_base64 must be the BARE base64 payload — no "data:...;base64," prefix.
    expect(body.data_base64).not.toMatch(/^data:/)
    expect(body.data_base64.length).toBeGreaterThan(0)

    expect(result.answer_text).toBe('Analysis complete.')
  })

  it('throws AuthError on 401', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 401 })
    const file = makeFile('notes.txt')
    await expect(analyzeReport(file, 'sess-123')).rejects.toBeInstanceOf(AuthError)
  })

  it('surfaces the backend detail message on failure', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 415,
      json: async () => ({ detail: "PDF analysis isn't supported yet." }),
    })
    const file = makeFile('notes.txt')
    await expect(analyzeReport(file, 'sess-123')).rejects.toThrow(/PDF analysis isn't supported/)
  })

  it('throws a generic error when the network request itself fails', async () => {
    global.fetch.mockRejectedValue(new TypeError('network down'))
    const file = makeFile('notes.txt')
    await expect(analyzeReport(file, 'sess-123')).rejects.toThrow(/cannot reach the server/i)
  })
})
