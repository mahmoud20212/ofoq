import { useEffect, useState } from "react";
import { getApplications, deleteConsent, useEnvironment, type AccountEnvironment } from "@keycloak/keycloak-account-ui";
import { Button, Modal, ModalVariant, Spinner } from "@patternfly/react-core";
import { Grid2X2 } from "lucide-react";
import styles from "./ConnectedApplications.module.css";

type Application = Awaited<ReturnType<typeof getApplications>>[number];
type PendingAction = { app: Application; kind: "sessions" | "consent" };

export function ConnectedApplications() {
  const context = useEnvironment<AccountEnvironment>();
  const { keycloak, environment } = context;
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const portalClientId = import.meta.env.VITE_PORTAL_CLIENT_ID || "ofoq-site";

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    getApplications({ context: { keycloak, environment }, signal: controller.signal })
      .then((items) => {
        if (!controller.signal.aborted) {
          // The portal and the account console are parts of the same user experience.
          // Keep their OIDC clients and sessions intact; hide only their list entries.
          setApps(items.filter((app) => app.clientId !== portalClientId && app.clientId !== environment.clientId));
        }
      })
      .catch(() => { if (!controller.signal.aborted) setError("تعذّر تحميل التطبيقات. حاول مجددًا."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [keycloak, environment, portalClientId, revision]);

  const appName = (app: Application) => app.clientName && !app.clientName.startsWith("${") ? app.clientName : app.clientId;
  const confirm = async () => {
    if (!pending || busy) return;
    setBusy(true);
    setError("");
    try {
      if (pending.kind === "consent") await deleteConsent(context, pending.app.clientId);
      else {
        await keycloak.updateToken(30);
        if (!keycloak.token) throw new Error("No session");
        const accountRoot = new URL(environment.baseUrl);
        if (!accountRoot.pathname.endsWith("/")) accountRoot.pathname += "/";
        const response = await fetch(new URL(`applications/${encodeURIComponent(pending.app.clientId)}/sessions`, accountRoot), {
          method: "DELETE", headers: { Authorization: `Bearer ${keycloak.token}`, Accept: "application/json" },
        });
        if (!response.ok) throw new Error("Session termination failed");
      }
      setNotice(pending.kind === "sessions" ? "تم إنهاء جلسات التطبيق." : "تم إلغاء وصول التطبيق.");
      setPending(null);
      setRevision((value) => value + 1);
    } catch { setError("تعذّر إكمال العملية. حاول مجددًا."); }
    finally { setBusy(false); }
  };

  if (loading) return <div className={styles.state}><Spinner aria-label="جارٍ تحميل التطبيقات" size="lg" /></div>;
  return <div className={styles.list}>
    {notice && <p className={styles.notice} role="status">{notice}</p>}
    {error && !pending && <div role="alert"><p>{error}</p><Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>إعادة المحاولة</Button></div>}
    {!error && apps.length === 0 && <div className={styles.state}>
      <span className={styles.emptyIcon}><Grid2X2 size={28} aria-hidden="true" /></span>
      <h2>لا توجد تطبيقات مرتبطة بعد</h2>
      <p>ستظهر هنا الخدمات الأخرى التي تمنحها صلاحية الوصول إلى حسابك. يمكنك إدارة حساب أُفق من القائمة الجانبية.</p>
      {/* <a href={import.meta.env.VITE_LANDING_PAGE_URL || "http://localhost:3000/"}>العودة إلى الرئيسية</a> */}
    </div>}
    {apps.map((app) => <article className={styles.application} key={app.clientId}>
      <div className={styles.details}>
        <h2>{appName(app)}</h2>
        {app.description && !app.description.startsWith("${") && <p>{app.description}</p>}
        <span className={styles.status}>{app.inUse || app.offlineAccess ? "جلسة نشطة" : "لا توجد جلسات نشطة"}</span>
        {app.consent?.grantedScopes.length ? <details><summary>صلاحيات الوصول</summary><ul>{app.consent.grantedScopes.map((scope) => <li key={scope.id}>{scope.displayText && !scope.displayText.startsWith("${") ? scope.displayText : scope.name}</li>)}</ul></details> : null}
      </div>
      <div className={styles.actions}>
        {(app.inUse || app.offlineAccess) && <Button variant="secondary" onClick={() => { setError(""); setNotice(""); setPending({ app, kind: "sessions" }); }}>إنهاء جلسة التطبيق</Button>}
        {(app.consent || app.offlineAccess) && <Button variant="secondary" onClick={() => { setError(""); setNotice(""); setPending({ app, kind: "consent" }); }}>إلغاء الوصول</Button>}
      </div>
    </article>)}
    <Modal variant={ModalVariant.small} title={pending?.kind === "consent" ? "إلغاء وصول التطبيق" : "إنهاء جلسة التطبيق"}
      isOpen={!!pending} onClose={() => { if (!busy) { setPending(null); setError(""); } }}
      actions={[
        <Button key="confirm" variant="primary" onClick={confirm} isDisabled={busy} isLoading={busy}>تأكيد</Button>,
        <Button key="cancel" variant="secondary" isDisabled={busy} onClick={() => { setPending(null); setError(""); }}>إلغاء</Button>,
      ]}>
      {pending && <p>{pending.kind === "sessions"
        ? `سيتم إنهاء جلساتك في ${appName(pending.app)}. سيبقى حساب أُفق مسجّلًا في المتصفح، وقد يعيد التطبيق تسجيل دخولك تلقائيًا عند فتحه مجددًا.`
        : `سيتم إلغاء الصلاحيات التي منحتها لتطبيق ${appName(pending.app)}. يمكنك ربطه مجددًا لاحقًا.`}</p>}
      {error && <p role="alert">{error}</p>}
    </Modal>
  </div>;
}
