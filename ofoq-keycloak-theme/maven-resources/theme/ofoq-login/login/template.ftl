<#import "footer.ftl" as loginFooter>
<#import "theme-resources.ftl" as themeResourceTags>
<#import "alerts.ftl" as alerts>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<#-- Match Keycloak's existing-identity state used by the header below. -->
<#assign ofoqKnownIdentity = (auth?has_content && auth.showUsername() && !auth.showResetCredentials()) || usernameHidden?? || isAppInitiatedAction??>
<#assign ofoqSplit = ((pageId!"") == "login" || (pageId!"") == "register") && !ofoqKnownIdentity>
<#assign ofoqReauth = ((pageId!"") == "login" || (pageId!"") == "login-password") && ofoqKnownIdentity>
<#assign ofoqDescriptions = {
 "login": "ofoqLoginDescription",
 "login-username": "ofoqLoginDescription",
 "login-password": "ofoqLoginDescription",
 "register": "ofoqRegisterDescription",
 "login-reset-password": "ofoqResetDescription",
 "login-update-password": "ofoqPasswordDescription",
 "login-config-totp": "ofoqSetupOtpDescription",
 "login-otp": "ofoqOtpDescription",
 "login-verify-email": "ofoqVerifyEmailDescription",
 "update-email": "ofoqUpdateEmailDescription",
 "logout-confirm": "ofoqLogoutDescription",
 "delete-credential": "ofoqDeleteCredentialDescription",
 "login-page-expired": "ofoqExpiredDescription",
 "error": "ofoqErrorDescription",
 "info": "ofoqInfoDescription"
}>
<#assign ofoqDescriptionKey = ofoqReauth?then("ofoqReauthDescription", ofoqDescriptions[pageId!""]!"ofoqDefaultDescription")>
<#assign ofoqTitles = {
 "login": "ofoqLoginTitle",
 "register": "ofoqRegisterTitle",
 "login-otp": "ofoqOtpTitle",
 "login-config-totp": "ofoqSetupOtpTitle",
 "login-reset-password": "ofoqResetTitle",
 "login-update-password": "updatePasswordTitle",
 "login-verify-email": "ofoqVerifyEmailTitle",
 "update-email": "ofoqUpdateEmailTitle",
 "logout-confirm": "ofoqLogoutTitle",
 "login-page-expired": "ofoqExpiredTitle"
}>
<!DOCTYPE html>
<html class="ofoq-document" lang="${lang}"<#if realm.internationalizationEnabled> dir="${(locale.rtl)?then('rtl','ltr')}"</#if>>

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />

    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <title>${title!}</title>
    <#if themeResources?? && themeResources.favicons?has_content>
        <@themeResourceTags.renderFavicons themeResources.favicons url.resourcesPath />
    <#else>
        <link rel="icon" href="${url.resourcesPath}/img/favicon.ico" />
    </#if>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <script src="${url.resourcesPath}/js/auth-theme.js"></script>
    <#if themeResources?? && themeResources.styles?has_content>
        <@themeResourceTags.renderStyles themeResources.styles url.resourcesPath />
    <#elseif properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if themeResources?? && themeResources.scripts?has_content>
        <@themeResourceTags.renderScripts themeResources.scripts url.resourcesPath "text/javascript" />
    <#elseif properties.scripts?has_content>
        <#list properties.scripts?split(' ') as script>
            <script src="${url.resourcesPath}/${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="importmap">
        {
            "imports": {
                "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"
            }
        }
    </script>
    <script src="${url.resourcesPath}/js/menu-button-links.js" type="module"></script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="module">
        <#outputformat "JavaScript">
        import { startSessionPolling } from ${(url.resourcesPath + "/js/authChecker.js")?c};

        startSessionPolling(
            ${url.ssoLoginInOtherTabsUrl?c}
        );
        </#outputformat>
    </script>
    <script type="module">
        document.addEventListener("click", (event) => {
            const link = event.target.closest("a[data-once-link]");

            if (!link) {
                return;
            }

            if (link.getAttribute("aria-disabled") === "true") {
                event.preventDefault();
                return;
            }

            const { disabledClass } = link.dataset;

            if (disabledClass) {
                link.classList.add(...disabledClass.trim().split(/\s+/));
            }

            link.setAttribute("role", "link");
            link.setAttribute("aria-disabled", "true");
        });
    </script>
    <#if authenticationSession??>
        <script type="module">
            <#outputformat "JavaScript">
            import { checkAuthSession } from ${(url.resourcesPath + "/js/authChecker.js")?c};

            checkAuthSession(
                ${authenticationSession.authSessionIdHash?c}
            );
            </#outputformat>
        </script>
    </#if>
</head>

<body class="ofoq-auth ${ofoqSplit?then('ofoq-auth-split','ofoq-auth-centered')} ${bodyClass}" data-page-id="login-${pageId}">
<main class="ofoq-auth-layout">
<section class="ofoq-form-panel" aria-labelledby="kc-page-title" aria-describedby="ofoq-page-description"><div class="ofoq-form-content">
    <div class="ofoq-form-brand">
        <img src="${url.resourcesPath}/img/ofoq-logo.png" alt="" />
        <strong>أُفق</strong>
    </div>
    <div class="${properties.kcFormCardClass!}">
        <header class="${properties.kcFormHeaderClass!}">
            <#if realm.internationalizationEnabled  && locale.supported?size gt 1>
                <div class="${properties.kcLocaleMainClass!}" id="kc-locale">
                    <div id="kc-locale-wrapper" class="${properties.kcLocaleWrapperClass!}">
                        <div id="kc-locale-dropdown" class="menu-button-links ${properties.kcLocaleDropDownClass!}">
                            <button tabindex="1" id="kc-current-locale-link" aria-label="${msg("languages")}" aria-haspopup="true" aria-expanded="false" aria-controls="language-switch1">${locale.current}</button>
                            <ul role="menu" tabindex="-1" aria-labelledby="kc-current-locale-link" aria-activedescendant="" id="language-switch1" class="${properties.kcLocaleListClass!}">
                                <#assign i = 1>
                                <#list locale.supported as l>
                                    <li class="${properties.kcLocaleListItemClass!}" role="none">
                                        <a role="menuitem" id="language-${i}" class="${properties.kcLocaleItemClass!}" href="${l.url}">${l.label}</a>
                                    </li>
                                    <#assign i++>
                                </#list>
                            </ul>
                        </div>
                    </div>
                </div>
            </#if>
        <#if (pageId!"") == "login-otp"><p class="ofoq-step-label">${msg("ofoqOtpStage")}</p></#if>
        <h1 id="kc-page-title"><#if ofoqReauth>${msg("ofoqReauthTitle")}<#elseif ofoqTitles[pageId!""]??>${msg(ofoqTitles[pageId])}<#else><#nested "header"></#if></h1>
        <p id="ofoq-page-description" class="ofoq-page-description">${msg(ofoqDescriptionKey)}</p>
        <#if displayRequiredFields>
            <p class="subtitle"><span class="required">*</span> ${msg("requiredFields")}</p>
        </#if>
        <#if auth?has_content && auth.showUsername() && !auth.showResetCredentials()>
            <#nested "show-username">
            <div id="kc-username" class="ofoq-identity">
                <span>${msg("ofoqAccountLabel")} <bdi>${auth.attemptedUsername}</bdi></span>
                <a id="reset-login" href="${url.loginRestartFlowUrl}">${msg("ofoqRestartLogin")}</a>
            </div>
        </#if>
      </header>
      <div id="kc-content">
        <div id="kc-content-wrapper">

          <#-- App-initiated actions should not see warning messages about the need to complete the action -->
          <#-- during login.                                                                               -->
          <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
              <@alerts.notice type=message.type>${kcSanitize(message.summary)?no_esc}</@alerts.notice>
          </#if>

          <#nested "form">

          <#if auth?has_content && auth.showTryAnotherWayLink()>
              <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                  <div class="${properties.kcFormGroupClass!}">
                      <input type="hidden" name="tryAnotherWay" value="on"/>
                      <a href="#" id="try-another-way"
                         onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
                  </div>
              </form>
          </#if>

          <#if switchOrganizationEnabled?? && switchOrganizationEnabled>
              <form id="kc-switch-organization-form" action="${url.loginAction}" method="post">
                  <div class="${properties.kcFormGroupClass!}">
                      <input type="hidden" name="switchOrganization" value="true"/>
                      <a href="#" id="switch-organization"
                         onclick="document.forms['kc-switch-organization-form'].requestSubmit();return false;">${msg("doSwitchOrganization")}</a>
                  </div>
              </form>
          </#if>

          <#nested "socialProviders">

          <#if displayInfo>
              <div id="kc-info" class="${properties.kcSignUpClass!}">
                  <div id="kc-info-wrapper" class="${properties.kcInfoAreaWrapperClass!}">
                      <#nested "info">
                  </div>
              </div>
          </#if>
        </div>
      </div>

      <@loginFooter.content/>
    </div>
  </div>
</section>
<#if ofoqSplit>
<aside class="ofoq-brand-panel" aria-label="أُفق">
 <div class="ofoq-brand-content">
  <div class="ofoq-brand-mark"><img src="${url.resourcesPath}/img/ofoq-logo.png" alt="" /><strong>أُفق</strong></div>
  <h2>معرفة تمتد<br>إلى ما هو أبعد.</h2>
  <p>حساب واحد يجمع رحلتك في مسار ووثوق وصلة.</p>
 </div>
</aside>
</#if>
</main>
</body>
</html>
</#macro>
