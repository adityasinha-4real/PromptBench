import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError, api, errorMessage } from '@/lib/api';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('api client', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the parsed body on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok', version: '1.0.0' }));
    await expect(api.health()).resolves.toMatchObject({ status: 'ok' });
  });

  it('serialises query parameters and drops empty ones', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }));
    await api.listBenchmarks({ search: 'tcp', provider: '', limit: 10 });

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe('/api/benchmarks');
    expect(url.searchParams.get('search')).toBe('tcp');
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.has('provider')).toBe(false);
  });

  it('unwraps the backend error envelope into a readable message', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'authentication',
            message: 'Gemini request failed: API key is missing.',
            hint: 'Check that the API key environment variable is set.',
          },
        },
        401
      )
    );

    await expect(api.getBenchmark(1)).rejects.toSatisfy((error: unknown) => {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(401);
      expect(apiError.code).toBe('authentication');
      expect(apiError.message).toBe('Gemini request failed: API key is missing.');
      expect(apiError.hint).toContain('environment variable');
      return true;
    });
  });

  it('never surfaces a bare status code when the body is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 }));
    const error = await api.health().catch((cause: ApiError) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain('Bad Gateway');
  });

  it('marks transient failures as retryable', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'rate_limit', message: 'Slow down.' } }, 429)
    );
    const error = (await api.health().catch((cause) => cause)) as ApiError;
    expect(error.retryable).toBe(true);
  });

  it('does not mark a validation failure as retryable', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'invalid_request', message: 'Bad prompt.' } }, 422)
    );
    const error = (await api.health().catch((cause) => cause)) as ApiError;
    expect(error.retryable).toBe(false);
  });

  it('reports an unreachable backend with an actionable hint', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const error = (await api.health().catch((cause) => cause)) as NetworkError;
    expect(error).toBeInstanceOf(NetworkError);
    expect(error.message).toContain('Could not reach');
    expect(error.hint).toContain('API running');
  });

  it('handles 204 responses without trying to parse a body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteBenchmark(1)).resolves.toBeUndefined();
  });

  it('sends JSON bodies with the right content type', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ provider: 'ollama', available: true, detail: 'ok' })
    );
    await api.testConnection('ollama', 'llama3.2');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body as string)).toEqual({ provider: 'ollama', model: 'llama3.2' });
  });

  it('reads the filename from Content-Disposition for exports', async () => {
    fetchMock.mockResolvedValue(
      new Response('a,b\n1,2', {
        status: 200,
        headers: {
          'Content-Type': 'text/csv',
          'Content-Disposition': 'attachment; filename="promptbench-1-tcp.csv"',
        },
      })
    );
    const file = await api.exportBenchmark(1, 'csv');
    expect(file.filename).toBe('promptbench-1-tcp.csv');
    expect(file.contentType).toBe('text/csv');
    expect(file.body).toContain('a,b');
  });

  it('builds the SSE stream URL', () => {
    expect(api.runStreamUrl(42)).toMatch(/\/api\/runs\/42\/stream$/);
  });
});

describe('errorMessage', () => {
  it('extracts a message from every shape a caller might throw', () => {
    expect(errorMessage(new ApiError(404, { code: 'not_found', message: 'Gone.' }))).toBe('Gone.');
    expect(errorMessage(new Error('boom'))).toBe('boom');
    expect(errorMessage('a string')).toBe('Something went wrong.');
  });
});
