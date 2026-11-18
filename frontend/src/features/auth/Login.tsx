import { useState, type FormEvent } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { ActionButton } from "../../components/ActionButton";
import { Icon } from "../../components/Icon";

export function Login() {
  const { service, session, storageWarning } = usePortal();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();

  if (session.status === "connecting") {
    return (
      <main className="login-shell" aria-busy="true">
        <div className="login-status" role="status">
          Connecting to the management API…
        </div>
      </main>
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(() => service.login(username, password));
  }

  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-brand">
          <Icon name="shield" size={28} />
          <span>SecureCloud</span>
        </div>
        <div className="login-copy">
          <h1 id="login-title">Sign in</h1>
          <p>Access the local zero-trust management console.</p>
        </div>
        {storageWarning && (
          <p className="warning-note" role="alert">
            {storageWarning}
          </p>
        )}
        <form onSubmit={submit} className="login-form">
          <label className="field">
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              minLength={3}
              maxLength={100}
              required
              autoFocus
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              maxLength={256}
              required
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <ActionButton className="button primary login-submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </ActionButton>
        </form>
        <p className="login-footnote">
          Local lab only. Accounts are created from the backend bootstrap
          command.
        </p>
      </section>
    </main>
  );
}
