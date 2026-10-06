import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type AskResponse,
  type Collection,
  type SearchStrategy,
} from "../api/client";
import { LoadingState } from "../components/LoadingState";
import { SourceCard } from "../components/SourceCard";

const STRATEGIES: { id: SearchStrategy; label: string }[] = [
  { id: "vector", label: "Vetorial" },
  { id: "text", label: "Textual" },
  { id: "hybrid", label: "Híbrida" },
];

export function AskPage() {
  const { collectionId = "" } = useParams();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [loading, setLoading] = useState(true);
  const [question, setQuestion] = useState("");
  const [strategy, setStrategy] = useState<SearchStrategy>("vector");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api.collection(collectionId)
      .then((data) => { if (current) setCollection(data); })
      .catch(() => { if (current) setError("Não foi possível abrir esta coleção."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [collectionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAsking(true);
    setAnswer(null);
    setError(null);
    try {
      setAnswer(await api.ask(collectionId, question.trim(), strategy));
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 503
        ? "Ollama indisponível. Inicie o serviço local e confira os modelos de embeddings e chat."
        : cause instanceof ApiError && cause.status === 401
          ? "Sua sessão expirou. Entre novamente para continuar."
          : "Não foi possível consultar os documentos desta coleção. Tente novamente.");
    } finally {
      setAsking(false);
    }
  }

  if (loading) return <div className="page-content"><LoadingState label="Preparando consulta…" /></div>;
  if (!collection) return <div className="page-content"><p className="notice notice-error" role="alert">{error || "Coleção não encontrada."}</p><Link to="/library">Voltar ao acervo</Link></div>;

  return (
    <div className="page-content ask-page">
      <nav aria-label="Trilha de navegação" className="breadcrumbs">
        <Link to="/library">Meu acervo</Link><span aria-hidden="true">/</span>
        <Link to={`/collections/${collection.id}`}>{collection.name}</Link><span aria-hidden="true">/</span><span>Consulta</span>
      </nav>
      <header className="page-header ask-page-header">
        <div>
          <p className="eyebrow">CONSULTA COM FONTES</p>
          <h1>Pergunte aos documentos</h1>
          <p className="page-subtitle">{collection.name} <span className="collection-context-dot">·</span> respostas apoiadas apenas no conteúdo da coleção.</p>
        </div>
      </header>

      <form className="question-panel" onSubmit={(event) => void submit(event)}>
        <label htmlFor="question-text">Sua pergunta</label>
        <textarea
          autoFocus
          id="question-text"
          maxLength={4_000}
          onChange={(event) => setQuestion(event.currentTarget.value)}
          placeholder="Ex.: O que significa o código E-17 neste modelo?"
          required
          rows={4}
          value={question}
        />
        <div className="question-controls">
          <div className="strategy-control">
            <label htmlFor="search-strategy">Modo de busca</label>
            <select
              id="search-strategy"
              onChange={(event) => setStrategy(event.currentTarget.value as SearchStrategy)}
              value={strategy}
            >
              {STRATEGIES.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </div>
          <button className="button button-primary ask-button" disabled={asking || !question.trim()} type="submit">
            {asking ? "Consultando…" : "Perguntar"}<span aria-hidden="true">→</span>
          </button>
        </div>
        <p className="query-note">A resposta usa somente os documentos desta coleção e mostra os trechos recuperados.</p>
      </form>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {asking && <LoadingState label="Buscando trechos e preparando uma resposta…" />}

      {answer && (
        <section aria-labelledby="answer-heading" className="answer-region">
          <div className="answer-heading-row">
            <div>
              <p className="eyebrow">RESPOSTA · {strategy.toUpperCase()}</p>
              <h2 id="answer-heading">Resultado da consulta</h2>
            </div>
            <span className="evidence-status"><span className="live-dot" />{answer.sources.length ? `${answer.sources.length} ${answer.sources.length === 1 ? "fonte" : "fontes"}` : "Sem fontes encontradas"}</span>
          </div>
          <div className="answer-copy"><p>{answer.answer}</p></div>
          {answer.sources.length > 0 ? (
            <div className="source-section">
              <div className="section-heading source-section-heading">
                <div><p className="eyebrow">RASTREABILIDADE</p><h3>Trechos usados</h3></div>
                <span className="mono-label">{answer.sources.length.toString().padStart(2, "0")} FONTES</span>
              </div>
              <div className="source-list">
                {answer.sources.map((source) => <SourceCard key={source.source_id} source={source} />)}
              </div>
            </div>
          ) : (
            <p className="no-sources-note" role="status">Nenhum trecho foi retornado para esta pergunta. Tente outro termo ou confira os documentos processados.</p>
          )}
        </section>
      )}

      {!answer && !asking && !error && (
        <section className="query-empty-state">
          <span className="query-glyph" aria-hidden="true">?</span>
          <div><p className="eyebrow">PRONTO PARA CONSULTAR</p><p>Faça uma pergunta específica. As fontes aparecem junto da resposta.</p></div>
        </section>
      )}
    </div>
  );
}
