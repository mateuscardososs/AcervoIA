import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppRoutes from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { TOKEN_KEY } from "./api/client";

const user = { id: "u-1", email: "tecnica@example.test" };
const collection = {
  id: "c-1",
  name: "Manuais de demonstração",
  description: "Equipamentos fictícios",
  created_at: "2026-10-06T12:00:00Z",
};
const documentRecord = {
  id: "d-1",
  original_filename: "manual-orion.txt",
  content_type: "text/plain",
  size_bytes: 64,
  created_at: "2026-10-06T12:00:00Z",
  processing_status: "pending",
  processing_error: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(
  handler: (path: string, init: RequestInit) => Response | Promise<Response>,
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), window.location.origin).pathname.replace(
      /^\/api/,
      "",
    );
    return Promise.resolve(handler(path, init));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mount(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function authenticate() {
  sessionStorage.setItem(TOKEN_KEY, "test-jwt");
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AcervoIA web flows", () => {
  it("logs in and guides an empty account to create its first collection", async () => {
    const fetchMock = installFetch((path, init) => {
      if (path === "/auth/token") {
        expect(init.body).toBeInstanceOf(URLSearchParams);
        return jsonResponse({ access_token: "test-jwt", token_type: "bearer" });
      }
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections" && init.method === "POST") {
        const payload = JSON.parse(String(init.body)) as Record<string, string>;
        return jsonResponse({ ...collection, name: payload.name }, 201);
      }
      if (path === "/collections") return jsonResponse([]);
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/login");

    await actor.type(screen.getByLabelText("E-mail"), user.email);
    await actor.type(screen.getByLabelText("Senha"), "private-password");
    await actor.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByText("Seu acervo ainda está vazio")).toBeVisible();
    await actor.click(screen.getByRole("button", { name: "Criar primeira coleção" }));
    await actor.type(screen.getByLabelText("Nome da coleção"), "Guias de bancada");
    await actor.click(screen.getByRole("button", { name: "Criar coleção" }));

    expect(await screen.findByText("Guias de bancada")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/collections",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("clears a newly issued token when the authenticated session cannot be confirmed", async () => {
    installFetch((path) => {
      if (path === "/auth/token") {
        return jsonResponse({ access_token: "new-jwt", token_type: "bearer" });
      }
      if (path === "/auth/me") {
        return jsonResponse({ detail: "temporary failure" }, 500);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/login");
    await actor.type(screen.getByLabelText("E-mail"), user.email);
    await actor.type(screen.getByLabelText("Senha"), "private-password");
    await actor.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Não foi possível entrar/);
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("uploads, processes and reports when Ollama cannot prepare embeddings", async () => {
    authenticate();
    let currentDocument = { ...documentRecord };
    let uploaded = false;
    const fetchMock = installFetch((path, init) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/documents" && init.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        uploaded = true;
        return jsonResponse(currentDocument, 201);
      }
      if (path === "/collections/c-1/documents") {
        return jsonResponse(uploaded ? [currentDocument] : []);
      }
      if (path.endsWith("/d-1/process")) {
        currentDocument = { ...currentDocument, processing_status: "completed" };
        return jsonResponse({ document_id: "d-1", processing_status: "completed", chunk_count: 3 });
      }
      if (path.endsWith("/d-1/embeddings")) {
        return jsonResponse({ detail: "Não foi possível usar o serviço local de embeddings." }, 503);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1");
    expect(await screen.findByRole("heading", { name: collection.name })).toBeVisible();

    const file = new File(["manual fictício"], "manual-orion.txt", { type: "text/plain" });
    await actor.upload(screen.getByLabelText("Enviar documento"), file);
    await actor.click(screen.getByRole("button", { name: "Enviar arquivo" }));

    expect(await screen.findByText("manual-orion.txt")).toBeVisible();
    await actor.click(screen.getByRole("link", { name: "Detalhes de manual-orion.txt" }));
    expect(await screen.findByRole("heading", { name: "manual-orion.txt" })).toBeVisible();
    await actor.click(screen.getByRole("button", { name: "Processar documento" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Ollama/i);
    expect(screen.getByRole("heading", { name: "Processado" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/collections/c-1/documents/d-1/process",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/collections/c-1/documents/d-1/embeddings",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("starts with vector search, sends each selected strategy and renders backend sources", async () => {
    authenticate();
    const askedWith: string[] = [];
    installFetch((path, init) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/ask") {
        const payload = JSON.parse(String(init.body)) as { strategy: string };
        askedWith.push(payload.strategy);
        return jsonResponse({
          answer: "Desligue o equipamento antes de limpar. [S1]",
          sources: [
            {
              source_id: "S1",
              document_id: "d-1",
              document_name: "manual-orion.txt",
              page_number: null,
              snippet: "A limpeza deve ser feita com o equipamento desligado.",
            },
          ],
        });
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");

    const mode = await screen.findByLabelText("Modo de busca");
    expect(mode).toHaveValue("vector");
    await actor.type(screen.getByLabelText("Sua pergunta"), "Como limpar?");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));
    expect(await screen.findByText(/Desligue o equipamento/)).toBeVisible();
    const source = screen.getByRole("article", { name: "Fonte S1" });
    expect(within(source).getByText("manual-orion.txt")).toBeVisible();
    expect(within(source).getByText(/limpeza deve ser feita/)).toBeVisible();
    expect(within(source).queryByText(/página/i)).not.toBeInTheDocument();

    await actor.selectOptions(mode, "text");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));
    await actor.selectOptions(mode, "hybrid");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));

    await waitFor(() => expect(askedWith).toEqual(["vector", "text", "hybrid"]));
  });

  it("shows saved questions with sources and lets the user ask one again", async () => {
    authenticate();
    const asked: Array<{ question: string; strategy: string; limit: number }> = [];
    const savedQuestion = {
      id: "h-1",
      question: "Qual é o procedimento salvo?",
      strategy: "hybrid",
      answer: "Desligue antes da limpeza. [S1]",
      sources: [
        {
          source_id: "S1",
          document_id: "d-1",
          document_name: "historico.txt",
          page_number: 3,
          snippet: "Desligue o equipamento antes de limpar.",
        },
      ],
      created_at: "2026-10-06T12:00:00Z",
    };
    installFetch((path, init) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/history") {
        return jsonResponse({ items: [savedQuestion], limit: 20, offset: 0, has_more: false });
      }
      if (path === "/collections/c-1/ask") {
        asked.push(JSON.parse(String(init.body)) as { question: string; strategy: string; limit: number });
        return jsonResponse({ answer: "Consulta atualizada.", sources: [] });
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");

    expect(await screen.findByText("Qual é o procedimento salvo?")).toBeVisible();
    const historicalSource = screen.getByRole("article", { name: "Fonte S1" });
    expect(within(historicalSource).getByText("historico.txt")).toBeVisible();
    expect(within(historicalSource).getByText("Página 3")).toBeVisible();
    await actor.click(screen.getByRole("button", { name: /consultar novamente/i }));

    expect(await screen.findByText("Consulta atualizada.")).toBeVisible();
    expect(asked).toEqual([{ question: savedQuestion.question, strategy: "hybrid", limit: 5 }]);
  });

  it("opens a cited PDF at its page and downloads a cited text file from history", async () => {
    authenticate();
    const historySource = {
      source_id: "S2",
      document_id: "d-txt",
      document_name: "manual-atlas.txt",
      page_number: null,
      snippet: "Confira o indicador antes da limpeza.",
    };
    const historyItem = {
      id: "h-2",
      question: "O que devo conferir?",
      strategy: "text",
      answer: "Confira o indicador. [S2]",
      sources: [historySource],
      created_at: "2026-10-06T12:00:00Z",
    };
    const openedWindow = {
      opener: window,
      location: { href: "" },
      close: vi.fn(),
    } as unknown as Window;
    vi.spyOn(window, "open").mockReturnValue(openedWindow);
    vi.spyOn(URL, "createObjectURL")
      .mockReturnValueOnce("blob:pdf-source")
      .mockReturnValueOnce("blob:text-source");
    const downloads: Array<{ href: string; download: string }> = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push({ href: this.href, download: this.download });
    });
    installFetch((path, init) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/history") {
        return jsonResponse({ items: [historyItem], limit: 20, offset: 0, has_more: false });
      }
      if (path === "/collections/c-1/ask") {
        expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-jwt");
        return jsonResponse({
          answer: "Confira o certificado. [S1]",
          sources: [{
            source_id: "S1",
            document_id: "d-pdf",
            document_name: "manual-orion.pdf",
            page_number: 7,
            snippet: "O certificado de calibração está no anexo.",
          }],
        });
      }
      if (path === "/collections/c-1/documents/d-pdf/file") {
        expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-jwt");
        return new Response("%PDF-original", { headers: { "Content-Type": "application/pdf" } });
      }
      if (path === "/collections/c-1/documents/d-txt/file") {
        return new Response("texto-original", { headers: { "Content-Type": "text/plain" } });
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");

    await actor.type(await screen.findByLabelText("Sua pergunta"), "Qual certificado?");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));
    await actor.click(await screen.findByRole("button", { name: "Abrir PDF na página 7" }));
    await waitFor(() => expect(openedWindow.location.href).toBe("blob:pdf-source#page=7"));
    await actor.click(screen.getByRole("button", { name: "Baixar arquivo original" }));

    expect(downloads).toEqual([{ href: "blob:text-source", download: "manual-atlas.txt" }]);
  });

  it("shows a friendly message when a cited original file is missing", async () => {
    authenticate();
    installFetch((path) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/history") {
        return jsonResponse({ items: [], limit: 20, offset: 0, has_more: false });
      }
      if (path === "/collections/c-1/ask") {
        return jsonResponse({
          answer: "Confira a página 7. [S1]",
          sources: [{
            source_id: "S1",
            document_id: "missing-pdf",
            document_name: "manual-orion.pdf",
            page_number: 7,
            snippet: "Trecho recuperado.",
          }],
        });
      }
      if (path === "/collections/c-1/documents/missing-pdf/file") {
        return jsonResponse({ detail: "O arquivo original não está mais disponível." }, 404);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    vi.spyOn(window, "open").mockReturnValue({
      opener: window,
      location: { href: "" },
      close: vi.fn(),
    } as unknown as Window);
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");

    await actor.type(await screen.findByLabelText("Sua pergunta"), "Qual o procedimento?");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));
    await actor.click(await screen.findByRole("button", { name: "Abrir PDF na página 7" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "O arquivo original não está mais disponível nesta coleção.",
    );
  });

  it("explains Ollama unavailability on a question without leaking a stack trace", async () => {
    authenticate();
    installFetch((path) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/ask") {
        return jsonResponse({ detail: "Não foi possível usar o serviço local de embeddings." }, 503);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");
    await actor.type(await screen.findByLabelText("Sua pergunta"), "Qual alimentação?");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Ollama/i);
    expect(screen.queryByText(/Traceback|stack trace/i)).not.toBeInTheDocument();
  });

  it("explains an invalid model response without presenting unverified sources", async () => {
    authenticate();
    installFetch((path) => {
      if (path === "/auth/me") return jsonResponse(user);
      if (path === "/collections/c-1") return jsonResponse(collection);
      if (path === "/collections/c-1/ask") {
        return jsonResponse({ detail: "internal model output" }, 502);
      }
      return jsonResponse({ detail: "not found" }, 404);
    });
    const actor = userEvent.setup();
    mount("/collections/c-1/ask");
    await actor.type(await screen.findByLabelText("Sua pergunta"), "Qual alimentação?");
    await actor.click(screen.getByRole("button", { name: "Perguntar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/não pôde ser validada/i);
    expect(screen.queryByText(/internal model output/i)).not.toBeInTheDocument();
  });
});
