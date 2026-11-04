// import { UserRound } from "lucide-react";
import { PersonalInfo } from "@keycloak/keycloak-account-ui";
import styles from "./ProfilePage.module.css";

export function ProfilePage() {
  return (
    <div className={styles.profilePage} dir="rtl">
      <div className={styles.pageHeading}>
        <div>
          <h1>الملف الشخصي</h1>
          <p>
            إدارة معلوماتك الشخصية المرتبطة بحساب أُفق الموحد
          </p>
        </div>
      </div>

      <div className={styles.profileCard}>
        <PersonalInfo />
      </div>
    </div>
  );
}
