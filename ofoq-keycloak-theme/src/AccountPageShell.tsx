import styles from "./AccountPageShell.module.css";
import panelStyles from "./AccountPanel.module.css";

type AccountPageShellProps = {
  title: string;
  description: string;
  children: React.ReactNode;
};

export function AccountPageShell({
  title,
  description,
  children,
}: AccountPageShellProps) {
  return (
    <div className={styles.page} dir="rtl">
      <header className={styles.pageHeader}>
        <div className={styles.headerCopy}>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>

      <section className={`${styles.card} ${panelStyles.panel}`}>{children}</section>
    </div>
  );
}
