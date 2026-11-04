# Ofoq authentication theme

Freemarker overrides belong directly in `login/`, beside `theme.properties`.
Do not put them in a `templates/` subdirectory: Keycloak will fall back to the
parent theme instead of loading those overrides.

The form templates are based on Keycloak 26.8.1's official base login theme.
The shared `template.ftl` keeps the upstream authentication/session scripts,
sanitized messages, alternate authentication, and form sections while providing
the Ofoq two-panel HTML structure. Registration uses the upstream dynamic User
Profile renderer. The email update template is named `update-email.ftl`.

Only `resources/css/ofoq-login.css` supplies layout styles; no PatternFly login
stylesheet or generated-content layout is required.

## Packaging

The JAR must contain `META-INF/keycloak-themes.json` and files such as
`theme/ofoq-login/login/template.ftl` and `theme/ofoq-login/login/login.ftl`.
React's build does not validate Freemarker templates.

Replace the previous theme provider JAR instead of adding another JAR declaring
the same theme names. Restart Keycloak after replacing a provider JAR. Select
`ofoq-login` as the realm's Login theme.

## Runtime verification

The rendered document must contain `ofoq-auth-layout`, `ofoq-form-panel`, and
`ofoq-brand-panel`; it must not contain `login-pf-page`.
Test login errors, registration with required realm attributes, password reset,
OTP credential selection, email verification/update, and logout confirmation.
