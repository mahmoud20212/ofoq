
import { Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Spinner } from "@patternfly/react-core";
import { Menu, X, Sun, Moon, House } from "lucide-react";
import { PageNav } from "./PageNav";

import styles from "./App.module.css";
import "./styles/tokens.css";
import "./styles/keycloak.css";
import "./styles/responsive.css";
import "./styles/controls.css";
import "./styles/notices.css";
import "./styles/dialogs.css";
import { useAccountTheme } from "./AccountTheme";


function App() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const { theme, toggleTheme } = useAccountTheme();

  useEffect(() => {
    document.documentElement.lang = "ar";
    document.documentElement.dir = "rtl";
  }, []);


  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };

    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, []);

  return (
    <div
      className={`${styles.account} account-theme`}
      data-theme={theme}
      dir="rtl"
      lang="ar"
    >
      <header className={`${styles.header} header`}>
        <div className={styles.headerStart}>
          <button
            type="button"
            className={`${styles.menuButton} menuButton`}
            onClick={() => setMenuOpen((open) => !open)}
            aria-label={menuOpen ? "إغلاق القائمة" : "فتح القائمة"}
            aria-expanded={menuOpen}
            aria-controls="account-navigation"
          >
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>

          <a className={styles.brand} href={import.meta.env.VITE_LANDING_PAGE_URL || "http://localhost:3000/"} aria-label="أُفق — الصفحة الرئيسية">
            <img
              src={`${import.meta.env.BASE_URL}ofoq-logo.png`}
              alt="شعار أُفق"
              className={`${styles.brandLogo} brandLogo`}
            />
            <div>
              <strong>أُفق</strong>
              <span>مركز الحسابات</span>
            </div>
          </a>
        </div>

        <div className={styles.headerActions}>
          <a className={styles.homeLink} href={import.meta.env.VITE_LANDING_PAGE_URL || "http://localhost:3000/"}
            aria-label="العودة للصفحة الرئيسية" title="العودة للصفحة الرئيسية">
            <House size={18} aria-hidden="true" />
            <span>الرئيسية</span>
          </a>
        <button
          type="button"
          className={`${styles.themeButton} themeButton`}
          onClick={toggleTheme}
          aria-label={
            theme === "dark"
              ? "تفعيل الوضع الفاتح"
              : "تفعيل الوضع الداكن"
          }
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          <span>
            {theme === "dark" ? "الوضع الفاتح" : "الوضع الداكن"}
          </span>
        </button>
        </div>
      </header>

      <div className={styles.layout}>
        {menuOpen && (
          <button
            type="button"
            className={`${styles.backdrop} backdrop`}
            onClick={() => setMenuOpen(false)}
            aria-label="إغلاق القائمة الجانبية"
          />
        )}

        <div
          id="account-navigation"
          className={[
            styles.sidebarWrapper,
            "sidebarWrapper",
            menuOpen ? styles.sidebarOpen : "",
            menuOpen ? "sidebarOpen" : "",
          ].join(" ")}
        >
          <PageNav />
        </div>

        <main
          className={`${styles.content} content`}
          id="main-content"
        >
          <div className={styles.pageContent}><Suspense
            fallback={
              <div className={styles.loading}>
                <Spinner aria-label="جارٍ التحميل" />
              </div>
            }
          >
            <Outlet />
          </Suspense></div>
          <footer className={styles.footer}>
            <span>حساب واحد، آفاق متعددة</span>
            <span>© {new Date().getFullYear()} أُفق. جميع الحقوق محفوظة.</span>
            {/* <a href={import.meta.env.VITE_LANDING_PAGE_URL || "http://localhost:3000/"}>الصفحة الرئيسية</a> */}
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;
