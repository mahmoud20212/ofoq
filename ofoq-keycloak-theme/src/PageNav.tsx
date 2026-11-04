
import { NavLink, useLocation } from "react-router-dom";
import { useState } from "react";
import { useEnvironment, type AccountEnvironment } from "@keycloak/keycloak-account-ui";
import {
  UserRound,
  ShieldCheck,
  MonitorSmartphone,
  Grid2X2,
  LayoutDashboard,
  ChevronLeft,
  LogOut,
} from "lucide-react";

import styles from "./App.module.css";

const navigation = [
  {
    label: "مركز الحسابات",
    path: "myPage",
    icon: LayoutDashboard,
  },
  {
    label: "الملف الشخصي",
    path: "",
    icon: UserRound,
    end: true,
  },
  {
    label: "الأمان وتسجيل الدخول",
    path: "account-security/signingIn",
    icon: ShieldCheck,
  },
  {
    label: "الأجهزة والجلسات",
    path: "account-security/deviceActivity",
    icon: MonitorSmartphone,
  },
  // {
  //   label: "الحسابات المرتبطة",
  //   path: "account-security/linkedAccounts",
  //   icon: Link2,
  // },
  {
    label: "التطبيقات المرتبطة",
    path: "applications",
    icon: Grid2X2,
  },
];

export function PageNav() {
  const location = useLocation();
  const { keycloak, environment } = useEnvironment<AccountEnvironment>();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");

  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    setLogoutError("");
    try {
      await keycloak.logout({ redirectUri: environment.baseUrl });
    } catch {
      setLogoutError("تعذّر تسجيل الخروج. حاول مرة أخرى.");
      setSigningOut(false);
    }
  };

  const accountRoot =
    location.pathname.split("/account/")[0] + "/account/";

  return (
    <aside className={`${styles.sidebar} sidebar`}>
      <div
        className={`${styles.sidebarHeading} sidebarHeading`}
      >
        إدارة الحساب
      </div>

      <nav aria-label="القائمة الرئيسية">
        <div className={`${styles.navList} navList`}>
          {navigation.map((item) => {
            const Icon = item.icon;

            return (
              <NavLink
                key={item.label}
                to={`${accountRoot}${item.path}`}
                end={item.end}
                className={({ isActive }) =>
                  [
                    styles.navItem,
                    isActive ? styles.navActive : "",
                  ].join(" ")
                }
              >
                <Icon
                  size={19}
                  strokeWidth={1.8}
                  aria-hidden="true"
                />
                <span>{item.label}</span>
                <ChevronLeft
                  size={15}
                  className={styles.navChevron}
                  aria-hidden="true"
                />
              </NavLink>
            );
          })}
        </div>
      </nav>

      <div className={styles.sidebarFooter}>
        <button
          type="button"
          className={styles.logoutButton}
          onClick={signOut}
          disabled={signingOut}
          aria-busy={signingOut}
        >
          <LogOut size={19} strokeWidth={1.8} aria-hidden="true" />
          <span>{signingOut ? "جارٍ تسجيل الخروج…" : "تسجيل الخروج"}</span>
        </button>
        {logoutError && <p className={styles.logoutError} role="alert">{logoutError}</p>}
        <strong>أُفق</strong>
        <p>حساب واحد، آفاق متعددة</p>
      </div>
    </aside>
  );
}
