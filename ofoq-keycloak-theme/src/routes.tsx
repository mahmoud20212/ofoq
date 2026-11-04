import type { IndexRouteObject, RouteObject } from "react-router-dom";
import App from "./App";
import { environment } from "./environment";
import {
  Applications,
  DeviceActivity,
  Groups,
  LinkedAccounts,
  // PersonalInfo,
  Resources,
  SigningIn,
} from "@keycloak/keycloak-account-ui";
import { MyPage } from "./MyPage";
import { ProfilePage } from "./ProfilePage";
import { AccountPageShell } from "./AccountPageShell";

export const DeviceActivityRoute: RouteObject = {
  path: "account-security/deviceActivity",
  element: (
    <AccountPageShell
      title="نشاط الأجهزة"
      description="قم بتسجيل الخروج من أي جهاز غير مألوف"
    >
      <DeviceActivity />
    </AccountPageShell>
  ),
};

export const LinkedAccountsRoute: RouteObject = {
  path: "account-security/linkedAccounts",
  element: (
    <AccountPageShell
      title="الحسابات المرتبطة"
      description="قم بإدارة تسجيل الدخول لحسابات الطرف الثالث المرتبطة بحسابك"
    >
      <LinkedAccounts />
    </AccountPageShell>
  ),
};

export const SigningInRoute: RouteObject = {
  path: "account-security/signingIn",
  element: (
    <AccountPageShell
      title="عملية تسجيل الدخول"
      description="إعداد طرق تسجيل الدخول وحماية حسابك"
    >
      <SigningIn />
    </AccountPageShell>
  ),
};

export const ApplicationsRoute: RouteObject = {
  path: "applications",
  element: (
    <AccountPageShell
      title="التطبيقات المرتبطة"
      description="قم بتتبع وإدارة أذونات التطبيقات للوصول إلى حسابك"
    >
      <Applications />
    </AccountPageShell>
  ),
};

export const GroupsRoute: RouteObject = {
  path: "groups",
  element: <Groups />,
};

export const ResourcesRoute: RouteObject = {
  path: "resources",
  element: <Resources />,
};

export const PersonalInfoRoute: IndexRouteObject = {
  index: true,
  element: <ProfilePage />,
};

export const MyPageRoute: RouteObject = {
  path: "myPage",
  element: <MyPage />,
};

export const RootRoute: RouteObject = {
  path: decodeURIComponent(new URL(environment.baseUrl).pathname),
  element: <App />,
  errorElement: <>Error</>,
  children: [
    PersonalInfoRoute,
    DeviceActivityRoute,
    LinkedAccountsRoute,
    SigningInRoute,
    ApplicationsRoute,
    GroupsRoute,
    ResourcesRoute,
    MyPageRoute,
  ],
};

export const routes: RouteObject[] = [RootRoute];
