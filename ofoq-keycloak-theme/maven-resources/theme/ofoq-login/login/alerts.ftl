<#macro notice type="info">
    <#local kind = ["success", "error", "warning", "info"]?seq_contains(type)?then(type, "info")>
    <div class="ofoq-alert ofoq-alert--${kind}" role="${(kind == 'error')?then('alert','status')}" aria-atomic="true">
        <svg class="ofoq-alert-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
            <#if kind == "success">
                <circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>
            <#elseif kind == "error">
                <circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>
            <#elseif kind == "warning">
                <path d="m12 3 10 18H2L12 3Zm0 6v5m0 3h.01"/>
            <#else>
                <circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>
            </#if>
        </svg>
        <div class="ofoq-alert-content">
            <strong>${msg("ofoqAlert." + kind)}</strong>
            <div><#nested></div>
        </div>
    </div>
</#macro>
