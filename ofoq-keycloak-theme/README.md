# Custom Keycloak Account UI

## Brand reference

The landing page and account center form the Ofoq portal. `ConnectedApplications`
lists other services using the official Keycloak account API, excluding the portal
client (`VITE_PORTAL_CLIENT_ID`, default `ofoq-site`) and the account console client.
This affects presentation only: OIDC clients, sessions, permissions, and SSO remain
managed by Keycloak. No client or user data is deleted by filtering the list.

Colors and action buttons follow `../ofoq-site/src/app/(frontend)/styles.css`.
Account tokens live in `src/styles/tokens.css`, including the tokens inherited
by body-portal dialogs. Account `--text` maps to the landing page's main text
token `--white`, while `--text-secondary` maps to its `--text`.
The login theme mirrors the same palette in `ofoq-login.css`. Primary actions
use the 135-degree purple/blue gradient, pill corners, and shared hover shadows;
compact icon controls keep an appropriate touch target.

The account welcome card greets the signed-in user. The shared account header
links back to the landing page at `http://localhost:3000/`. For another environment, set
`VITE_LANDING_PAGE_URL` to that site's URL before running `npm run build`.

This is a template to build a custom Keycloak Account UI using the [Keycloak Account UI](https://npmjs.com/package/@keycloak/keycloak-account-ui) package.

## Getting started

To use HMR (Hot module replacement) in development, run the following command:

```bash
pnpm i
pnpm run dev
```
Then start the Keycloak server:

```bash
pnpm run start-keycloak
```

open the admin-console in your browser (http://localhost:8080/), when you the go to the `Manage Account` by clicking on the name in the toolbar, you will see the custom UI.

## Build

To build the application for production, run the following command:

```bash
mvn install
```
This will create a "jar" file in the `target` directory that you can deploy to your Keycloak server by copying it to the `providers` directory.
