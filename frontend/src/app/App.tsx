import { ActionButton } from "../components/ActionButton";
import { SuccessNotice } from "../components/SuccessNotice";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useAction, usePortal } from "./PortalContext";
import { Icon, type IconName } from "../components/Icon";
import { Modal } from "../components/ui";
import { Login } from "../features/auth/Login";

const Overview = lazy(() =>
  import("../features/overview/Overview").then((module) => ({
    default: module.Overview,
  })),
);
const Workloads = lazy(() =>
  import("../features/workloads/Workloads").then((module) => ({
    default: module.Workloads,
  })),
);
const WorkloadInspector = lazy(() =>
  import("../features/workloads/Workloads").then((module) => ({
    default: module.WorkloadInspector,
  })),
);
const CreateTenant = lazy(() =>
  import("../features/workloads/CreateTenant").then((module) => ({
    default: module.CreateTenant,
  })),
);
const Catalog = lazy(() =>
  import("../features/catalog/Catalog").then((module) => ({
    default: module.Catalog,
  })),
);
const Network = lazy(() =>
  import("../features/network/Network").then((module) => ({
    default: module.Network,
  })),
);
const Incidents = lazy(() =>
  import("../features/incidents/Incidents").then((module) => ({
    default: module.Incidents,
  })),
);

type View = "overview" | "workloads" | "catalog" | "network" | "incidents";
const views: { id: View; name: string; icon: IconName; description: string }[] =
  [
    {
      id: "overview",
      name: "Overview",
      icon: "grid",
      description: "Your resources and security activity, in one place.",
    },
    {
      id: "workloads",
      name: "Tenants & Workloads",
      icon: "layers",
      description: "Create tenant workspaces and manage their resources.",
    },
    {
      id: "catalog",
      name: "Catalog",
      icon: "box",
      description: "Deploy an approved template to your tenant.",
    },
    {
      id: "network",
      name: "Network Map",
      icon: "network",
      description:
        "Explore tenant boundaries and simulate connection decisions.",
    },
    {
      id: "incidents",
      name: "Incidents",
      icon: "alert",
      description:
        "Investigate alerts, contain workloads, and review recovery.",
    },
  ];
function getView(): View {
  return (
    views.find((v) => `#${v.id}` === window.location.hash)?.id ?? "overview"
  );
}

export default function App() {
  const { mode, session } = usePortal();
  if (mode === "api" && session.status !== "signed-in") return <Login />;
  return <ConsoleApp />;
}

function ConsoleApp() {
  const {
    data,
    scopedData,
    storageWarning,
    service,
    session,
    mode,
    tenantId,
    selectTenant,
  } = usePortal();
  const [view, setView] = useState<View>(getView);
  const [clearOpen, setClearOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [navHidden, setNavHidden] = useState(false);
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [inspectId, setInspectId] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const { busy, error, run } = useAction();
  useEffect(() => {
    const onHash = () => setView(getView());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.title = `${views.find((v) => v.id === view)!.name} · SecureCloud`;
  }, [view]);
  function navigate(next: View) {
    window.location.hash = next;
    setView(next);
    setQuery("");
    setNotice("");
    requestAnimationFrame(() => {
      heading.current?.focus();
      window.scrollTo({ top: 0 });
    });
  }
  function loadDemo() {
    void run(
      () => service.loadDemo(),
      () => {
        selectTenant("");
        navigate("overview");
        setNotice(
          "Demo loaded: College and Hospital are ready with six sample workloads. Your other tenants are unchanged.",
        );
      },
    );
  }
  const current = views.find((v) => v.id === view)!;
  const active = scopedData.incidents.filter(
    (i) => i.status !== "restored",
  ).length;
  const search = query.trim().toLowerCase();
  const foundViews = search
    ? views.filter((v) => v.name.toLowerCase().includes(search))
    : [];
  const foundTenants = search
    ? data.tenants
        .filter((t) => t.name.toLowerCase().includes(search))
        .slice(0, 4)
    : [];
  const foundWorkloads = search
    ? data.workloads.filter((w) => w.name.includes(search)).slice(0, 6)
    : [];
  const hasWorkspaceData = Boolean(
    data.tenants.length ||
    data.workloads.length ||
    data.traffic.length ||
    data.incidents.length ||
    storageWarning,
  );
  return (
    <div
      className={`app-shell cloud-console ${navHidden ? "navigation-hidden" : ""}`}
    >
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="console-header">
        <button
          className="header-menu"
          aria-label="Toggle navigation"
          aria-expanded={!navHidden}
          aria-controls="portal-navigation"
          onClick={() => setNavHidden((v) => !v)}
        >
          <span />
          <span />
          <span />
        </button>
        <a
          className="console-brand"
          aria-label="SecureCloud home"
          href="#overview"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <Icon name="shield" size={25} />
          <span>SecureCloud</span>
        </a>
        {hasWorkspaceData && (
          <div className="global-search">
            <label>
              <Icon name="search" size={17} />
              <input
                aria-label="Search resources and services"
                placeholder="Search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setQuery("");
                }}
                autoComplete="off"
              />
            </label>
            {search && (
              <div
                className="search-results"
                role="region"
                aria-label="Search results"
              >
                {foundViews.map((v) => (
                  <button key={v.id} onClick={() => navigate(v.id)}>
                    <Icon name={v.icon} size={17} />
                    <span>
                      {v.name}
                      <small>Service</small>
                    </span>
                  </button>
                ))}
                {foundTenants.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      selectTenant(t.id);
                      navigate("workloads");
                    }}
                  >
                    <Icon name="layers" size={17} />
                    <span>
                      {t.name}
                      <small>Tenant</small>
                    </span>
                  </button>
                ))}
                {foundWorkloads.map((w) => (
                  <button
                    key={w.id}
                    onClick={() => {
                      setQuery("");
                      setInspectId(w.id);
                    }}
                  >
                    <Icon name={w.templateId} size={17} />
                    <span>
                      {w.name}
                      <small>
                        {data.tenants.find((t) => t.id === w.tenantId)?.name}
                      </small>
                    </span>
                  </button>
                ))}
                {!foundViews.length &&
                  !foundTenants.length &&
                  !foundWorkloads.length && (
                    <p>No matching resources or services.</p>
                  )}
              </div>
            )}
          </div>
        )}
        <div className="header-tools">
          {mode === "demo" && !data.demoLoaded && (
            <button
              className="load-demo-button"
              disabled={busy}
              onClick={loadDemo}
            >
              Load demo
            </button>
          )}
          {mode === "demo" && hasWorkspaceData && (
            <button
              className="header-settings"
              aria-label="Clear workspace"
              title="Clear workspace"
              onClick={() => setClearOpen(true)}
            >
              <Icon name="settings" size={19} />
            </button>
          )}
          {mode === "api" && session.status === "signed-in" ? (
            <button
              className="legacy-user"
              title={`Sign out ${session.user.username}`}
              aria-label={`Sign out ${session.user.username}`}
              onClick={() => void run(() => service.logout())}
            >
              {session.user.username.slice(0, 2).toUpperCase()}
            </button>
          ) : (
            <span
              className="legacy-user"
              title="Local operator · no authentication"
            >
              LO
            </span>
          )}
        </div>
      </header>
      <aside className="sidebar" id="portal-navigation" hidden={navHidden}>
        <nav aria-label="Main navigation">
          {views.map((item) => (
            <div key={item.id}>
              <a
                href={`#${item.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  navigate(item.id);
                }}
                aria-current={view === item.id ? "page" : undefined}
                className={view === item.id ? "active" : ""}
              >
                <Icon name={item.icon} size={18} />
                <span>{item.name}</span>
                {item.id === "incidents" && active > 0 && (
                  <b className="nav-count">{active}</b>
                )}
              </a>
            </div>
          ))}
        </nav>
      </aside>
      <div className="main-shell">
        <main id="main-content" tabIndex={-1}>
          <div className="page-heading">
            <h1 tabIndex={-1} ref={heading}>
              {current.name}
            </h1>
            {data.tenants.length > 0 && (
              <label className="scope-selector">
                <span className="sr-only">Tenant scope</span>
                <select
                  aria-label="Tenant scope"
                  value={tenantId}
                  onChange={(e) => selectTenant(e.target.value)}
                >
                  <option value="">All tenants</option>
                  {data.tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {storageWarning && (
            <p className="warning-note" role="alert">
              {storageWarning}
            </p>
          )}
          <SuccessNotice message={notice} />
          {error && !clearOpen && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <Suspense
            fallback={
              <div className="view-loading" role="status">
                Loading view…
              </div>
            }
          >
            <div key={`${tenantId}:${data.demoLoaded}`}>
              {view === "overview" && (
                <Overview
                  navigate={navigate}
                  onCreateTenant={() => setCreateOpen(true)}
                  onLoadDemo={loadDemo}
                  busy={busy}
                />
              )}
              {view === "workloads" && (
                <Workloads
                  onDeploy={() => navigate("catalog")}
                  onCreateTenant={() => setCreateOpen(true)}
                />
              )}
              {view === "catalog" && (
                <Catalog onCreateTenant={() => setCreateOpen(true)} />
              )}
              {view === "network" && (
                <Network onIncidents={() => navigate("incidents")} />
              )}
              {view === "incidents" && (
                <Incidents onNetwork={() => navigate("network")} />
              )}
            </div>
          </Suspense>
        </main>
      </div>
      {createOpen && (
        <Suspense fallback={null}>
          <CreateTenant
            onClose={() => setCreateOpen(false)}
            onCreated={() => {
              setCreateOpen(false);
              navigate("workloads");
              setNotice(
                "Tenant created. You can now deploy a workload from the catalog.",
              );
            }}
          />
        </Suspense>
      )}
      {inspectId && (
        <Suspense fallback={null}>
          <WorkloadInspector
            id={inspectId}
            onClose={() => setInspectId(null)}
          />
        </Suspense>
      )}
      {clearOpen && (
        <Modal
          title="Clear this workspace?"
          onClose={() => setClearOpen(false)}
        >
          <p>
            Remove all locally saved tenants, workloads, traffic, and incidents
            from this workspace. You will start with an empty console.
          </p>
          <p className="muted">
            You can use Load demo again to add the sample scenario. Other
            browser data is unaffected.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <ActionButton
              className="button"
              onClick={() => setClearOpen(false)}
            >
              Cancel
            </ActionButton>
            <ActionButton
              className="button danger"
              disabled={busy}
              onClick={() =>
                void run(
                  () => service.reset(),
                  () => {
                    selectTenant("");
                    setClearOpen(false);
                    navigate("overview");
                    setNotice("Workspace cleared.");
                  },
                )
              }
            >
              Clear all local data
            </ActionButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
