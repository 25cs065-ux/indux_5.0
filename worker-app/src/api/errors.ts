export type ApiErrorKind =
  /** 422, or a request rejected before sending (e.g. empty question). */
  | 'validation'
  /** 503: AI or database temporarily unavailable. */
  | 'unavailable'
  /** Any other non-2xx status. */
  | 'http'
  /** Request never reached the server (offline, DNS, CORS, server down). */
  | 'network'
  | 'timeout'
  /** Caller cancelled the request (e.g. a newer question replaced it). */
  | 'aborted'
  /** HTTP 200 but the body does not match the contract. */
  | 'malformed'

/** Error thrown by the API client. `message` is safe to show to workers. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number | undefined

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }

  /** Whether trying the same request again might succeed. */
  get retryable(): boolean {
    return this.kind === 'unavailable' || this.kind === 'network' || this.kind === 'timeout'
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}
