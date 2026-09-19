/*
 * Builds one structured audit record per request (allowed or denied).
 * ML-AuditLog writes it to Cloud Logging, which feeds the BigQuery
 * "AI control tower" views. Shared by both gateway proxies.
 */
(function () {
  function v(name) {
    var value = context.getVariable(name);
    return (value === null || value === undefined || String(value) === '') ? null : String(value);
  }
  function n(name) {
    var value = v(name);
    return value === null ? null : parseInt(value, 10);
  }

  var FAULT_DECISIONS = {
    QuotaViolation: 'denied:token_quota_exceeded',
    SpikeArrestViolation: 'denied:rate_limited',
    InvalidApiKey: 'denied:invalid_agent_key',
    FailedToResolveAPIKey: 'denied:missing_agent_key',
    ApiKeyNotApproved: 'denied:agent_key_revoked',
    consumer_key_expired: 'denied:agent_key_expired',
    app_not_approved: 'denied:agent_app_revoked',
    developer_status_not_active: 'denied:agent_owner_inactive',
    InvalidApiKeyForGivenResource: 'denied:agent_not_entitled'
  };

  var fault = v('fault.name');
  var decision = v('gw.decision') || 'allowed';
  if (fault && decision === 'allowed') {
    decision = FAULT_DECISIONS[fault] || ('error:' + fault);
  }
  context.setVariable('gw.decision', decision);

  var status = n('message.status.code') || n('response.status.code') || n('error.status.code');
  var started = n('client.received.start.timestamp');

  var record = {
    event: 'ai_gateway_request',
    gateway: v('apiproxy.name'),
    request_id: v('messageid'),
    agent: v('gw.agent') || v('developer.app.name') || 'unknown',
    agent_cloud: v('gw.agent_cloud') || 'unknown',
    api_product: v('apiproduct.name'),
    client_ip: v('client.ip'),
    method: v('request.verb'),
    path: v('proxy.pathsuffix'),
    status: status,
    decision: decision,
    latency_ms: started ? (new Date().getTime() - started) : null,
    llm: {
      model: v('llm.model'),
      backend: v('llm.backend'),
      prompt_tokens: n('llm.prompt_tokens'),
      completion_tokens: n('llm.completion_tokens'),
      total_tokens: n('llm.total_tokens'),
      safety_check: v('llm.armor_state'),
      safety_filters: v('llm.armor_reasons')
    },
    tool: {
      system: v('tool.system'),
      protocol: v('tool.protocol'),
      mcp_method: v('mcp.method'),
      name: v('tool.name'),
      pii_masked: v('tool.pii_masked') === 'true',
      hidden_tools: n('tool.hidden_count')
    }
  };

  context.setVariable('gw.audit_json', JSON.stringify(record));
  context.setVariable('response.header.x-ai-gateway-decision', decision);
})();
