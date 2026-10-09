export const TOKEN_KEY = "acervoia.accessToken";
export const SESSION_EXPIRED_EVENT = "acervoia:session-expired";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type AuthenticatedUser = { id: string; email: string };
export type Collection = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
};
export type DocumentRecord = {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  processing_status: "pending" | "processing" | "completed" | "failed";
  processing_error: string | null;
};

export type DocumentTaskRecord = {
  id: string;
  task_type: "process" | "embeddings";
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  attempt_count: number;
  error: string | null;
  result_count: number | null;
  embedding_model: string | null;
  created_at: string;
  updated_at: string;
};
export type SearchStrategy = "vector" | "text" | "hybrid";
export type AskSource = {
  source_id: string;
  document_id: string;
  document_name: string;
  page_number: number | null;
  snippet: string;
};
export type AskResponse = { answer: string; sources: AskSource[] };
export type AskHistoryItem = {
  id: string;
  question: string;
  strategy: SearchStrategy;
  document_ids: string[];
  answer: string;
  sources: AskSource[];
  created_at: string;
};
export type AskHistoryPage = {
  items: AskHistoryItem[];
  limit: number;
  offset: number;
  has_more: boolean;
};

const apiBase = import.meta.env.VITE_API_BASE_URL || "/api";

export function setAccessToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

async function readError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Use a stable client message when the backend has no JSON error payload.
  }
  return "Não foi possível concluir a operação.";
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body instanceof URLSearchParams && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8");
  }

  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (response.status === 401) {
    clearAccessToken();
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestBlob(path: string): Promise<Blob> {
  const headers = new Headers({ Accept: "*/*" });
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${apiBase}${path}`, { headers });
  if (response.status === 401) {
    clearAccessToken();
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return response.blob();
}

function jsonBody(value: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}

export const api = {
  login(email: string, password: string) {
    const body = new URLSearchParams({ username: email, password });
    return request<{ access_token: string; token_type: string }>("/auth/token", {
      method: "POST",
      body,
    });
  },
  me() {
    return request<AuthenticatedUser>("/auth/me");
  },
  collections() {
    return request<Collection[]>("/collections");
  },
  collection(id: string) {
    return request<Collection>(`/collections/${encodeURIComponent(id)}`);
  },
  createCollection(name: string, description: string) {
    return request<Collection>(
      "/collections",
      jsonBody({ name, description: description || null }),
    );
  },
  updateCollection(id: string, name: string, description: string) {
    return request<Collection>(
      `/collections/${encodeURIComponent(id)}`,
      { ...jsonBody({ name, description: description || null }), method: "PATCH" },
    );
  },
  deleteCollection(id: string) {
    return request<void>(`/collections/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },
  documents(collectionId: string) {
    return request<DocumentRecord[]>(
      `/collections/${encodeURIComponent(collectionId)}/documents`,
    );
  },
  uploadDocument(collectionId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<DocumentRecord>(
      `/collections/${encodeURIComponent(collectionId)}/documents`,
      { method: "POST", body },
    );
  },
  deleteDocument(collectionId: string, documentId: string) {
    return request<void>(
      `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}`,
      { method: "DELETE" },
    );
  },
  processDocument(collectionId: string, documentId: string) {
    return request<DocumentTaskRecord>(
      `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/process`,
      { method: "POST" },
    );
  },
  embedDocument(collectionId: string, documentId: string) {
    return request<DocumentTaskRecord>(
      `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/embeddings`,
      { method: "POST" },
    );
  },
  documentTask(collectionId: string, documentId: string, taskId: string) {
    return request<DocumentTaskRecord>(
      `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/tasks/${encodeURIComponent(taskId)}`,
    );
  },
  ask(
    collectionId: string,
    question: string,
    strategy: SearchStrategy,
    documentIds: string[] = [],
  ) {
    return request<AskResponse>(
      `/collections/${encodeURIComponent(collectionId)}/ask`,
      jsonBody({ question, limit: 5, strategy, document_ids: documentIds }),
    );
  },
  questionHistory(collectionId: string, limit = 20, offset = 0) {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return request<AskHistoryPage>(
      `/collections/${encodeURIComponent(collectionId)}/history?${params.toString()}`,
    );
  },
  documentFile(collectionId: string, documentId: string) {
    return requestBlob(
      `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/file`,
    );
  },
};
