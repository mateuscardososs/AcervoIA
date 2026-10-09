import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export function AppShell() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  function leave() {
    signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navegação principal">
        <NavLink className="brand" to="/library" aria-label="AcervoIA, ir ao acervo">
          <span className="brand-mark" aria-hidden="true">A</span>
          <span className="brand-name">Acervo<span>IA</span></span>
        </NavLink>

        <div className="sidebar-rule" />
        <p className="sidebar-label">ESPAÇO DE TRABALHO</p>
        <NavLink className={({ isActive }) => `nav-item${isActive ? " is-active" : ""}`} to="/library">
          <span className="nav-glyph" aria-hidden="true">▤</span>
          <span>Meu acervo</span>
        </NavLink>
        <div className="sidebar-note">
          <span className="live-dot" />
          <span>Fontes verificáveis</span>
        </div>

        <div className="sidebar-bottom">
          <div className="signed-in-as">
            <span className="avatar" aria-hidden="true">{user?.email.slice(0, 1).toUpperCase()}</span>
            <span className="signed-in-email" title={user?.email}>{user?.email}</span>
          </div>
          <button className="nav-item sign-out" type="button" onClick={leave}>
            <span className="nav-glyph" aria-hidden="true">↗</span>
            <span>Sair</span>
          </button>
        </div>
      </aside>
      <main className="main-region">
        {user?.is_demo && (
          <div className="demo-session-banner" role="status">
            Demonstração · dados fictícios · somente leitura. Perguntas/trechos podem ir ao Gemini; não envie dados sensíveis.
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
