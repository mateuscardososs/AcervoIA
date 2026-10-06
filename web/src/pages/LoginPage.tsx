import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function LoginPage() {
  const { signIn, signingIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await signIn(email, password);
      navigate("/library", { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? "E-mail ou senha incorretos."
          : "Não foi possível entrar. Verifique a conexão com o AcervoIA e tente novamente.",
      );
    }
  }

  return (
    <main className="login-page">
      <section className="login-intro" aria-label="Sobre o AcervoIA">
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">A</span>
          <span className="brand-name">Acervo<span>IA</span></span>
        </div>
        <div className="login-thesis">
          <p className="eyebrow eyebrow-light">BIBLIOTECA TÉCNICA PESSOAL</p>
          <h1>Encontre a instrução certa.<br /><span>Confira a fonte.</span></h1>
          <p className="login-description">
            Seus manuais, organizados por coleção. Respostas acompanhadas pelos trechos que as sustentam.
          </p>
        </div>
        <div className="folio-preview" aria-hidden="true">
          <span className="folio-rule" />
          <span className="folio-tag">[S1]</span>
          <span className="folio-line folio-line-long" />
          <span className="folio-line" />
          <span className="folio-source">manual · trecho 04</span>
        </div>
        <p className="login-footnote">O acesso é privado à sua conta.</p>
      </section>

      <section className="login-panel">
        <div className="login-form-wrap">
          <p className="eyebrow">ACESSO PRIVADO</p>
          <h2>Entrar no acervo</h2>
          <p className="muted-copy">Use o e-mail e a senha da sua conta.</p>

          <form className="stack-form login-form" onSubmit={submit}>
            <label htmlFor="login-email">E-mail</label>
            <input
              autoComplete="username"
              id="login-email"
              name="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <label htmlFor="login-password">Senha</label>
            <input
              autoComplete="current-password"
              id="login-password"
              name="password"
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {error && <p className="inline-error" role="alert">{error}</p>}
            <button className="button button-primary login-submit" disabled={signingIn} type="submit">
              {signingIn ? "Entrando…" : "Entrar"}
              <span aria-hidden="true">→</span>
            </button>
          </form>
          <p className="login-private-note"><span aria-hidden="true">⌑</span> Não há cadastro público. Peça acesso ao administrador do acervo.</p>
        </div>
      </section>
    </main>
  );
}
